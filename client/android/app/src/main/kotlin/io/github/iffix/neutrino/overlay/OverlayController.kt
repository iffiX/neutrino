package io.github.iffix.neutrino.overlay

import android.util.Log
import io.github.iffix.neutrino.CLIENT_LOG_TAG
import io.github.iffix.neutrino.OVERLAY_CONNECT_TIMEOUT_S
import io.github.iffix.neutrino.OVERLAY_PROBE_INTERVAL_MILLIS
import io.github.iffix.neutrino.OVERLAY_STOP_TIMEOUT_S
import io.github.iffix.neutrino.binding.BindingStore
import io.github.iffix.neutrino.binding.HubBinding
import io.github.iffix.neutrino.channel.ChannelOverlay
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.HubConnection
import io.github.iffix.neutrino.channel.HubView
import java.io.IOException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * Each hub's virtual network as three states, `off`, `connecting` and `on`, driven only by a
 * person's press: a connect is one attempt of at most 60 s, ended by the engine's address and
 * the hub's channel through the network, by a failure, or by Cancel. A console that has the
 * phone registered and has assigned no network holds the attempt with no deadline until it
 * assigns one, which starts a fresh 60 s, or until Cancel. Nothing retries, nothing moves to
 * another network, and nothing changes the pick. The VPN runs one network at a time.
 *
 * @param store The bindings, where the pick and the last state are kept.
 * @param launcher What starts and stops the VPN service.
 * @param scope Where the attempt's deadline and its asks run.
 * @param probe Whether the hub answers at an address; asked every 2 s from the engine's address on,
 *   until the hub answers at its address on the network.
 * @param onChannelPrefers Called with a hub and its address on the network once the hub answers
 *   there, so its channel runs through the network; with an empty address once the network is off.
 */
class OverlayController(
    private val store: BindingStore,
    private val launcher: OverlayLauncher,
    private val scope: CoroutineScope,
    private val probe: suspend (String) -> Boolean,
    private val onChannelPrefers: (String, String) -> Unit,
) {
    private val lock = Any()
    private val current = MutableStateFlow<Map<String, OverlayLine>>(emptyMap())
    private var active: Attempt? = null
    private var timer: Job? = null
    private var asking: Job? = null
    private var views: List<HubView> = emptyList()

    /** Every hub's virtual network by binding id; a hub not in the map is off with no error. */
    val lines: StateFlow<Map<String, OverlayLine>> = current.asStateFlow()

    /**
     * Connect once a hub whose network was on when the app last ran, and follow the bindings
     * and the channels from now on.
     *
     * @param views Every hub's view.
     */
    fun start(views: Flow<List<HubView>>) {
        store.bindings.value.firstOrNull { it.isOverlayOn }?.let { connect(it.id) }
        scope.launch {
            combine(store.bindings, views) { bindings, hubs -> bindings to hubs }
                .collect { (bindings, hubs) -> follow(bindings, hubs) }
        }
    }

    /**
     * Press Connect: one attempt on the hub's picked network. A press while any network is not
     * off is dropped.
     *
     * @param bindingId The hub.
     */
    fun connect(bindingId: String) = synchronized(lock) {
        if (active != null) {
            Log.i(CLIENT_LOG_TAG, "a virtual network runs; the connect of $bindingId is dropped")
            return@synchronized
        }
        val binding = store.get(bindingId) ?: return@synchronized
        val overlay = OverlayChoice.preferred(binding)
        if (overlay == null) {
            put(bindingId, OverlayLine(error = ChannelResult.refused("overlay_missing")))
            return@synchronized
        }
        active = Attempt(bindingId, overlay.provider, OverlayChoice.hubUrl(binding, overlay))
        put(bindingId, OverlayLine(OverlayState.CONNECTING, overlay.provider, job = OverlayJob.CONNECTING))
        restartTimer(OVERLAY_CONNECT_TIMEOUT_S) { expired(bindingId) }
        launcher.start(bindingId, overlay.provider)
    }

    /**
     * Press Cancel: the attempt ends and the engine stops.
     *
     * @param bindingId The hub.
     */
    fun cancel(bindingId: String) = synchronized(lock) {
        if (active?.bindingId != bindingId || line(bindingId).state != OverlayState.CONNECTING) return@synchronized
        end(bindingId, null)
    }

    /**
     * Press Disconnect: the engine stops, and the network is off once it says so.
     *
     * @param bindingId The hub.
     */
    fun disconnect(bindingId: String) = synchronized(lock) {
        val line = line(bindingId)
        if (active?.bindingId != bindingId || line.state != OverlayState.ON || line.job != OverlayJob.NONE) {
            return@synchronized
        }
        put(bindingId, line.copy(job = OverlayJob.DISCONNECTING))
        restartTimer(OVERLAY_STOP_TIMEOUT_S) {
            synchronized(lock) {
                if (active?.bindingId ==
                    bindingId
                ) {
                    end(bindingId, null)
                }
            }
        }
        launcher.stop()
    }

    /**
     * Pick which of a hub's networks the next connect joins; only while the hub's network is off.
     *
     * @param bindingId The hub.
     * @param provider The network's provider.
     */
    fun pick(bindingId: String, provider: String) = synchronized(lock) {
        if (active?.bindingId == bindingId || line(bindingId).state != OverlayState.OFF) return@synchronized
        put(bindingId, line(bindingId).copy(error = null))
        try {
            store.update(bindingId) { it.copy(overlayChoice = provider) }
        } catch (_: IOException) {
            put(bindingId, line(bindingId).copy(error = ChannelResult.refused("overlay_wish_unsaved")))
        }
    }

    /**
     * Take what the running engine says.
     *
     * @param status The engine's word.
     */
    fun report(status: OverlayStatus) = synchronized(lock) {
        val attempt = active ?: return@synchronized
        if (status.bindingId != attempt.bindingId || status.provider != attempt.provider) return@synchronized
        val line = line(attempt.bindingId)
        when (status.phase) {
            OverlayPhase.ON -> if (status.address.isNotEmpty()) {
                attempt.hasAddress = true
                put(attempt.bindingId, line.copy(address = status.address, isWaiting = false))
                if (line.isWaiting) restartTimer(OVERLAY_CONNECT_TIMEOUT_S) { expired(attempt.bindingId) }
                if (line.state == OverlayState.CONNECTING && asking == null) ask(attempt)
            }

            OverlayPhase.WAITING -> if (line.state == OverlayState.CONNECTING && !attempt.hasAddress) {
                timer?.cancel()
                timer = null
                put(attempt.bindingId, line.copy(isWaiting = true))
            }

            OverlayPhase.OFF, OverlayPhase.FAILED -> if (line.job == OverlayJob.DISCONNECTING) {
                end(attempt.bindingId, null, isStopped = true)
            } else {
                end(attempt.bindingId, status.refusal ?: ChannelResult.refused("overlay_engine_stopped"))
            }

            OverlayPhase.JOINING, OverlayPhase.LEAVING -> Unit
        }
    }

    /** The person took the VPN away in the phone's settings: the network is off. */
    fun revoked() = synchronized(lock) {
        active?.let { end(it.bindingId, ChannelResult.refused("overlay_not_authorized")) }
    }

    /**
     * A hub is being left: its network stops and its line goes.
     *
     * @param bindingId The hub.
     */
    fun forget(bindingId: String) = synchronized(lock) {
        if (active?.bindingId == bindingId) end(bindingId, null)
        current.update { it - bindingId }
    }

    /** A refresh: every line's error goes; the states stay. */
    fun clearErrors() = synchronized(lock) {
        current.update { lines -> lines.mapValues { (_, line) -> line.copy(error = null) } }
    }

    /**
     * Follow the bindings and the channels: a network the hub withdrew ends, and a connect whose
     * channel came up through the network is on.
     *
     * @param bindings Every binding.
     * @param hubs Every hub's view.
     */
    internal fun follow(bindings: List<HubBinding>, hubs: List<HubView>) = synchronized(lock) {
        views = hubs
        val attempt = active ?: return@synchronized
        val binding = bindings.firstOrNull { it.id == attempt.bindingId }
        when {
            binding == null -> {
                end(attempt.bindingId, null)
                current.update { it - attempt.bindingId }
            }

            binding.overlays.none { it.provider == attempt.provider } -> end(
                attempt.bindingId,
                ChannelResult.refused("overlay_withdrawn", "network" to ChannelOverlay(attempt.provider).title),
            )

            else -> settle()
        }
    }

    private fun settle() {
        val attempt = active ?: return
        val line = line(attempt.bindingId)
        if (line.state != OverlayState.CONNECTING || !attempt.hasAddress) return
        val hub = views.firstOrNull { it.binding.id == attempt.bindingId } ?: return
        val isUp = hub.connection == HubConnection.CONNECTED || hub.connection == HubConnection.DISABLED
        if (!isUp || (attempt.hubUrl.isNotEmpty() && hub.connectedAddress != attempt.hubUrl)) return
        timer?.cancel()
        timer = null
        put(attempt.bindingId, line.copy(state = OverlayState.ON, job = OverlayJob.NONE))
        keepOn(attempt.bindingId, true)
    }

    private fun ask(attempt: Attempt) {
        asking = scope.launch {
            while (attempt.hubUrl.isNotEmpty() && !probe(attempt.hubUrl)) delay(OVERLAY_PROBE_INTERVAL_MILLIS)
            synchronized(lock) {
                if (active !== attempt) return@synchronized
                onChannelPrefers(attempt.bindingId, attempt.hubUrl)
                settle()
            }
        }
    }

    private fun expired(bindingId: String) = synchronized(lock) {
        val attempt = active?.takeIf { it.bindingId == bindingId } ?: return@synchronized
        if (line(bindingId).state != OverlayState.CONNECTING) return@synchronized
        val code = if (attempt.hasAddress) "overlay_hub_unreachable" else "overlay_no_address"
        end(bindingId, ChannelResult.refused(code))
    }

    private fun end(bindingId: String, error: ChannelResult.Refused?, isStopped: Boolean = false) {
        val attempt = active ?: return
        active = null
        timer?.cancel()
        timer = null
        asking?.cancel()
        asking = null
        if (!isStopped) launcher.stop()
        put(bindingId, OverlayLine(network = attempt.provider, error = error))
        keepOn(bindingId, false)
        onChannelPrefers(bindingId, "")
    }

    private fun restartTimer(seconds: Long, onExpiry: () -> Unit) {
        timer?.cancel()
        timer = scope.launch {
            delay(seconds * 1000)
            onExpiry()
        }
    }

    private fun line(bindingId: String): OverlayLine = current.value[bindingId] ?: OverlayLine()

    private fun put(bindingId: String, line: OverlayLine) {
        current.update { it + (bindingId to line) }
    }

    private fun keepOn(bindingId: String, isOn: Boolean) {
        try {
            store.update(bindingId) { if (it.isOverlayOn == isOn) it else it.copy(isOverlayOn = isOn) }
        } catch (_: IOException) {
            Log.w(CLIENT_LOG_TAG, "the virtual network's last state of $bindingId was not kept")
        }
    }

    private class Attempt(val bindingId: String, val provider: String, val hubUrl: String) {
        var hasAddress = false
    }
}
