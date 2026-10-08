package io.github.iffix.neutrino.overlay

import android.util.Log
import io.github.iffix.neutrino.CLIENT_LOG_TAG
import io.github.iffix.neutrino.OVERLAY_LOGIN_TIMEOUT_S
import io.github.iffix.neutrino.OVERLAY_STOP_TIMEOUT_S
import io.github.iffix.neutrino.binding.BindingStore
import io.github.iffix.neutrino.binding.HubBinding
import io.github.iffix.neutrino.channel.ChannelLocalNetwork
import io.github.iffix.neutrino.channel.ChannelOverlay
import io.github.iffix.neutrino.channel.ChannelOverlayRoute
import io.github.iffix.neutrino.channel.ChannelResult
import java.io.IOException
import java.net.InetAddress
import java.net.UnknownHostException
import java.util.Locale
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * Each hub's virtual network as two states, `off` and `on`, driven only by a person's press. A
 * connect is the job `connecting` with one stage, `login`: the engine starts, logs in and gets an
 * address within 90 s, and the line is `on` once it has one, whatever the hub's channel does. A
 * console that has the phone registered and has assigned no network holds the stage with no
 * deadline until it assigns one, or until Cancel. Nothing retries, nothing moves to another
 * network, and nothing changes the pick. The VPN runs one network at a time. The stage's start
 * and end is one log line with its duration.
 *
 * @param store The bindings, where the pick and the last state are kept.
 * @param launcher What starts and stops the VPN service.
 * @param scope Where the stage's deadline runs.
 * @param clock The time in milliseconds, for the stage's duration in the log.
 * @param onPeersChanged Called with a hub whose network is on when the engine's peer list changed.
 * @param onNetworkChanged Called with a hub and its network once the network is on, and with
 *   null once it is off.
 */
class OverlayController(
    private val store: BindingStore,
    private val launcher: OverlayLauncher,
    private val scope: CoroutineScope,
    private val clock: () -> Long = System::currentTimeMillis,
    private val onPeersChanged: (String) -> Unit = {},
    private val onNetworkChanged: (String, ChannelOverlayRoute?) -> Unit,
) {
    private val lock = Any()
    private val current = MutableStateFlow<Map<String, OverlayLine>>(emptyMap())
    private var active: Attempt? = null
    private var timer: Job? = null

    /** Every hub's virtual network by binding id; a hub not in the map is off with no error. */
    val lines: StateFlow<Map<String, OverlayLine>> = current.asStateFlow()

    /** Connect once a hub whose network was on when the app last ran, and follow the bindings from now on. */
    fun start() {
        store.bindings.value.firstOrNull { it.isOverlayOn }?.let { connect(it.id) }
        scope.launch { store.bindings.collect { follow(it) } }
    }

    /**
     * Press Connect: one attempt on the hub's picked network, in its `login` stage. A press while
     * any network runs is dropped.
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
                OverlayState.OFF,
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
     * Press Cancel: the connect ends, and the engine stops.
     *
     * @param bindingId The hub.
     */
    fun cancel(bindingId: String) = synchronized(lock) {
        if (active?.bindingId != bindingId || line(bindingId).job != OverlayJob.CONNECTING) return@synchronized
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
        if (line(bindingId).job != OverlayJob.NONE) return@synchronized
        put(bindingId, line(bindingId).copy(error = null))
        try {
            store.update(bindingId) { it.copy(overlayChoice = provider) }
        } catch (_: IOException) {
            put(bindingId, line(bindingId).copy(error = ChannelResult.refused("overlay_wish_unsaved")))
        }
    }

    /**
     * Take what the running engine says. An address in the `login` stage puts the line `on`.
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
                    turnOn(attempt, line, address, prefix)
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

    /**
     * The running engine's peer list changed: a peer appeared or went. A network that is on
     * passes it to its hub as a network change.
     *
     * @param bindingId The hub whose network the engine runs.
     * @param provider The network's provider.
     */
    fun peersChanged(bindingId: String, provider: String) = synchronized(lock) {
        val attempt = active ?: return@synchronized
        if (attempt.bindingId != bindingId || attempt.provider != provider) return@synchronized
        if (line(bindingId).state != OverlayState.ON) return@synchronized
        log(attempt, "the peer list changed")
        onPeersChanged(bindingId)
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
     * Follow the bindings: a network the hub withdrew ends.
     *
     * @param bindings Every binding.
     */
    internal fun follow(bindings: List<HubBinding>) = synchronized(lock) {
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
        }
    }

    private fun turnOn(attempt: Attempt, line: OverlayLine, address: String, prefix: Int) {
        log(attempt, "stage login ended after ${elapsed(attempt)}: address $address/$prefix")
        timer?.cancel()
        timer = null
        put(
            attempt.bindingId,
            line.copy(
                state = OverlayState.ON,
                address = address,
                job = OverlayJob.NONE,
                isWaiting = false,
                stage = OverlayStage.NONE,
            ),
        )
        keepOn(attempt.bindingId, true)
        val binding = store.get(attempt.bindingId) ?: return
        val overlay = binding.overlays.firstOrNull { it.provider == attempt.provider } ?: return
        val url = OverlayChoice.hubUrl(binding, overlay, address, prefix)
        if (url.isEmpty()) return
        onNetworkChanged(attempt.bindingId, ChannelOverlayRoute(url, attempt.provider, networkOf(address, prefix)))
    }

    private fun networkOf(address: String, prefix: Int): ChannelLocalNetwork? = try {
        ChannelLocalNetwork(InetAddress.getByName(address), prefix)
    } catch (_: UnknownHostException) {
        null
    }

    private fun expired(bindingId: String) = synchronized(lock) {
        if (active?.bindingId != bindingId) return@synchronized
        val line = line(bindingId)
        if (line.job != OverlayJob.CONNECTING || line.stage != OverlayStage.LOGIN) return@synchronized
        end(bindingId, ChannelResult.refused("overlay_no_address"))
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
        if (!isStopped) launcher.stop()
        put(bindingId, OverlayLine(network = attempt.provider, error = error))
        keepOn(bindingId, false)
        onNetworkChanged(bindingId, null)
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

    private class Attempt(val bindingId: String, val provider: String, val stageStartedAt: Long)
}
