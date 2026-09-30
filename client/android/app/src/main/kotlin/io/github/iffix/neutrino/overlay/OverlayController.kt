package io.github.iffix.neutrino.overlay

import io.github.iffix.neutrino.OVERLAY_CHECK_INTERVAL_S
import io.github.iffix.neutrino.binding.BindingStore
import io.github.iffix.neutrino.binding.HubBinding
import io.github.iffix.neutrino.channel.HubView
import java.io.IOException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.launch

/**
 * The per-hub wish to be on a hub's virtual network, made true one network at a time: the wish
 * and the pick are kept on the binding; the running network follows [OverlayChoice].
 *
 * @param store The bindings, where the wish and the pick are kept.
 * @param launcher What starts and stops the VPN service.
 * @param clock Milliseconds that only move forward.
 * @param onFailover Called with a binding's id after its network moved, so its channel reconnects over the new one.
 */
class OverlayController(
    private val store: BindingStore,
    private val launcher: OverlayLauncher,
    private val clock: () -> Long,
    private val onFailover: (String) -> Unit,
) {
    private val current = MutableStateFlow<OverlayStatus?>(null)
    private val downSince = mutableMapOf<String, Long>()
    private var running: Pair<String, String>? = null

    /** What the running engine last said, null while no network runs. */
    val status: StateFlow<OverlayStatus?> = current.asStateFlow()

    /**
     * Follow the bindings and the channels, and look again every few seconds.
     *
     * @param scope Where the loop runs.
     * @param views Every hub's view.
     */
    fun start(scope: CoroutineScope, views: Flow<List<HubView>>) {
        val ticks = flow {
            while (true) {
                emit(Unit)
                delay(OVERLAY_CHECK_INTERVAL_S * 1000)
            }
        }
        scope.launch {
            combine(store.bindings, views, ticks) { bindings, hubs, _ -> bindings to hubs }
                .collect { (bindings, hubs) -> reconcile(bindings, hubs) }
        }
    }

    /**
     * Want, or stop wanting, one hub's network; wanting one hub's clears every other hub's wish.
     *
     * @param bindingId The hub.
     * @param isWanted The wish.
     */
    fun setWanted(bindingId: String, isWanted: Boolean) {
        for (binding in store.bindings.value) {
            val wish = binding.id == bindingId && isWanted
            if (binding.isOverlayWanted != wish) keep(binding.id) { it.copy(isOverlayWanted = wish) }
        }
    }

    /**
     * Pick which of a hub's networks to join; a network running for that hub moves to it.
     *
     * @param bindingId The hub.
     * @param provider The network's provider.
     */
    fun pick(bindingId: String, provider: String) {
        if (running?.first == bindingId) running = null
        keep(bindingId) { it.copy(overlayChoice = provider) }
    }

    /**
     * Take what the running engine says.
     *
     * @param status The engine's word.
     */
    fun report(status: OverlayStatus) {
        if (running == status.bindingId to status.provider || status.phase == OverlayPhase.OFF) current.value = status
    }

    /** The person took the VPN away in the phone's settings: every wish goes. */
    fun revoked() {
        running = null
        current.value = null
        store.bindings.value.filter { it.isOverlayWanted }.forEach { binding ->
            keep(binding.id) { it.copy(isOverlayWanted = false) }
        }
    }

    /**
     * Make the running network what the wish, the pick and the channels say it should be.
     *
     * @param bindings Every binding.
     * @param hubs Every hub's view.
     */
    internal fun reconcile(bindings: List<HubBinding>, hubs: List<HubView>) {
        val now = clock()
        for (hub in hubs) {
            if (hub.isConnected) downSince.remove(hub.binding.id) else downSince.putIfAbsent(hub.binding.id, now)
        }
        val wanted = bindings.firstOrNull { it.isOverlayWanted }
        val runningHere = running?.takeIf { it.first == wanted?.id }?.second
        val target = wanted?.let {
            OverlayChoice.decide(it, runningHere, downSince[it.id]?.let { since -> now - since })
        }
        if (wanted == null || target == null) {
            if (running != null) {
                running = null
                launcher.stop()
            }
            return
        }
        if (running == wanted.id to target) return
        running = wanted.id to target
        current.value = OverlayStatus(wanted.id, target, OverlayPhase.JOINING)
        launcher.start(wanted.id, target)
        if (runningHere != null && runningHere != target) {
            downSince.remove(wanted.id)
            onFailover(wanted.id)
        }
    }

    private fun keep(bindingId: String, change: (HubBinding) -> HubBinding) {
        try {
            store.update(bindingId, change)
        } catch (_: IOException) {
            // The wish stays as it was; the next change writes again.
        }
    }
}
