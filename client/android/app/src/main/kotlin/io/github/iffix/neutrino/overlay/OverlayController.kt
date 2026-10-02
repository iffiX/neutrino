package io.github.iffix.neutrino.overlay

import android.util.Log
import io.github.iffix.neutrino.CLIENT_LOG_TAG
import io.github.iffix.neutrino.OVERLAY_HUB_TIMEOUT_S
import io.github.iffix.neutrino.OVERLAY_LOGIN_TIMEOUT_S
import io.github.iffix.neutrino.OVERLAY_PROBE_INTERVAL_MILLIS
import io.github.iffix.neutrino.OVERLAY_STOP_TIMEOUT_S
import io.github.iffix.neutrino.binding.BindingStore
import io.github.iffix.neutrino.binding.HubBinding
import io.github.iffix.neutrino.channel.ChannelOverlay
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.HubConnection
import io.github.iffix.neutrino.channel.HubView
import java.io.IOException
import java.util.Locale
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
 * person's press. A connect is one attempt in two stages, each with its own limit: `login`, the
 * engine's start, login and address, within 90 s; then `hub`, within 60 s of the address, where
 * the hub's own address on the network is probed and, once it answers, the hub's channel runs
 * through that address and no other until the channel is up there, which is `on`. A console
 * that has the phone registered and has assigned no network holds the `login` stage with no
 * deadline until it assigns one, or until Cancel. Nothing retries, nothing moves to another
 * network, and nothing changes the pick. The VPN runs one network at a time. Each stage's start
 * and end is one log line with its duration.
 *
 * @param store The bindings, where the pick and the last state are kept.
 * @param launcher What starts and stops the VPN service.
 * @param scope Where the stages' deadlines and the probes run.
 * @param probe Whether the hub answers at an address; asked every 2 s through the `hub` stage
 *   until the hub answers at its address on the network.
 * @param clock The time in milliseconds, for the stages' durations in the log.
 * @param onChannelPrefers Called with a hub, its address on the network and whether the channel
 *   tries that address only: only, once the hub answers there in the `hub` stage; first, once
 *   the network is on; with an empty address once the network is off.
 */
class OverlayController(
    private val store: BindingStore,
    private val launcher: OverlayLauncher,
    private val scope: CoroutineScope,
    private val probe: suspend (String) -> Boolean,
    private val clock: () -> Long = System::currentTimeMillis,
    private val onChannelPrefers: (String, String, Boolean) -> Unit,
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
     * Press Connect: one attempt on the hub's picked network, starting with the `login` stage. A
     * press while any network is not off is dropped.
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
        val attempt = Attempt(bindingId, overlay.provider, clock())
        active = attempt
        put(
            bindingId,
            OverlayLine(
                OverlayState.CONNECTING,
                overlay.provider,
                job = OverlayJob.CONNECTING,
                stage = OverlayStage.LOGIN,
            ),
        )
        log(attempt, "stage login started")
        restartTimer(OVERLAY_LOGIN_TIMEOUT_S) { expired(bindingId) }
        launcher.start(bindingId, overlay.provider)
    }

    /**
     * Press Cancel: the attempt ends in whichever stage it is, and the engine stops.
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
                if (active?.bindingId == bindingId) end(bindingId, null)
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
     * Take what the running engine says. An address in the `login` stage starts the `hub` stage.
     *
     * @param status The engine's word.
     */
    fun report(status: OverlayStatus) = synchronized(lock) {
        val attempt = active ?: return@synchronized
        if (status.bindingId != attempt.bindingId || status.provider != attempt.provider) return@synchronized
        val line = line(attempt.bindingId)
        when (status.phase) {
            OverlayPhase.ON -> if (status.address.isNotEmpty()) {
                val address = status.address.substringBefore('/')
                val prefix = status.address.substringAfter('/', "32").toIntOrNull() ?: 32
                if (line.stage == OverlayStage.LOGIN) {
                    beginHub(attempt, line, address, prefix)
                } else {
                    put(attempt.bindingId, line.copy(address = address))
                }
            }

            OverlayPhase.WAITING -> if (line.stage == OverlayStage.LOGIN) {
                timer?.cancel()
                timer = null
                put(attempt.bindingId, line.copy(isWaiting = true))
                log(attempt, "the console has the phone registered; the login stage waits with no limit")
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
     * Follow the bindings and the channels: a network the hub withdrew ends, and a `hub` stage
     * whose channel came up through the hub's address on the network is on.
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

    private fun beginHub(attempt: Attempt, line: OverlayLine, address: String, prefix: Int) {
        log(attempt, "stage login ended after ${elapsed(attempt)}: address $address/$prefix")
        attempt.stageStartedAt = clock()
        val binding = store.get(attempt.bindingId)
        val overlay = binding?.overlays?.firstOrNull { it.provider == attempt.provider }
        attempt.hubUrl = if (binding != null && overlay != null) {
            OverlayChoice.hubUrl(binding, overlay, address, prefix)
        } else {
            ""
        }
        put(attempt.bindingId, line.copy(address = address, isWaiting = false, stage = OverlayStage.HUB))
        log(attempt, "stage hub started: probing ${attempt.hubUrl.ifEmpty { "no address of the hub" }}")
        restartTimer(OVERLAY_HUB_TIMEOUT_S) { expired(attempt.bindingId) }
        ask(attempt)
    }

    private fun settle() {
        val attempt = active ?: return
        val line = line(attempt.bindingId)
        if (line.state != OverlayState.CONNECTING || line.stage != OverlayStage.HUB || !attempt.isAnswered) return
        val hub = views.firstOrNull { it.binding.id == attempt.bindingId } ?: return
        val isUp = hub.connection == HubConnection.CONNECTED || hub.connection == HubConnection.DISABLED
        if (!isUp || (attempt.hubUrl.isNotEmpty() && hub.connectedAddress != attempt.hubUrl)) return
        timer?.cancel()
        timer = null
        log(attempt, "stage hub ended after ${elapsed(attempt)}: the channel runs through ${hub.connectedAddress}")
        put(attempt.bindingId, line.copy(state = OverlayState.ON, job = OverlayJob.NONE, stage = OverlayStage.NONE))
        keepOn(attempt.bindingId, true)
        if (attempt.hubUrl.isNotEmpty()) onChannelPrefers(attempt.bindingId, attempt.hubUrl, false)
    }

    private fun ask(attempt: Attempt) {
        asking?.cancel()
        asking = scope.launch {
            while (attempt.hubUrl.isNotEmpty() && !probe(attempt.hubUrl)) delay(OVERLAY_PROBE_INTERVAL_MILLIS)
            synchronized(lock) {
                if (active !== attempt) return@synchronized
                attempt.isAnswered = true
                if (attempt.hubUrl.isNotEmpty()) {
                    log(attempt, "the hub answers at ${attempt.hubUrl}; the channel tries only it")
                    onChannelPrefers(attempt.bindingId, attempt.hubUrl, true)
                }
                settle()
            }
        }
    }

    private fun expired(bindingId: String) = synchronized(lock) {
        if (active?.bindingId != bindingId) return@synchronized
        val line = line(bindingId)
        if (line.state != OverlayState.CONNECTING) return@synchronized
        val code = if (line.stage == OverlayStage.HUB) "overlay_hub_unreachable" else "overlay_no_address"
        end(bindingId, ChannelResult.refused(code))
    }

    private fun end(bindingId: String, error: ChannelResult.Refused?, isStopped: Boolean = false) {
        val attempt = active ?: return
        val stage = line(bindingId).stage
        if (stage != OverlayStage.NONE) {
            log(attempt, "stage ${stage.wireName} ended after ${elapsed(attempt)}: ${error?.code ?: "cancelled"}")
        }
        active = null
        timer?.cancel()
        timer = null
        asking?.cancel()
        asking = null
        if (!isStopped) launcher.stop()
        put(bindingId, OverlayLine(network = attempt.provider, error = error))
        keepOn(bindingId, false)
        onChannelPrefers(bindingId, "", false)
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

    private fun elapsed(attempt: Attempt): String =
        String.format(Locale.ROOT, "%.1f s", (clock() - attempt.stageStartedAt) / 1000.0)

    private fun log(attempt: Attempt, text: String) {
        Log.i(CLIENT_LOG_TAG, "virtual network ${attempt.provider} of ${attempt.bindingId}: $text")
    }

    private class Attempt(val bindingId: String, val provider: String, var stageStartedAt: Long) {
        var hubUrl = ""
        var isAnswered = false
    }
}
