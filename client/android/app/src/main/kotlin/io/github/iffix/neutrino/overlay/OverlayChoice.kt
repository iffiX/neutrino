package io.github.iffix.neutrino.overlay

import io.github.iffix.neutrino.CLIENT_OVERLAY_FAILOVER_S
import io.github.iffix.neutrino.binding.HubBinding
import io.github.iffix.neutrino.channel.ChannelOverlay

/**
 * Which of a hub's virtual networks the phone joins: the person's pick, else the hub's first,
 * and the next one once the hub's channel has been lost for [CLIENT_OVERLAY_FAILOVER_S] or the
 * one joined is no longer published.
 */
object OverlayChoice {
    /**
     * The network a hub's binding prefers.
     *
     * @param binding The binding.
     * @return The picked network while the hub still publishes it, else the hub's first, else null.
     */
    fun preferred(binding: HubBinding): ChannelOverlay? =
        binding.overlays.firstOrNull { it.provider == binding.overlayChoice } ?: binding.overlays.firstOrNull()

    /**
     * The network after one, in the hub's order and round again.
     *
     * @param binding The binding.
     * @param provider The network joined now.
     * @return The next other network, or null when the hub publishes no other.
     */
    fun next(binding: HubBinding, provider: String): ChannelOverlay? {
        val overlays = binding.overlays
        val index = overlays.indexOfFirst { it.provider == provider }
        if (index < 0) return overlays.firstOrNull()
        return (1 until overlays.size).map { overlays[(index + it) % overlays.size] }.firstOrNull()
    }

    /**
     * What should run for one binding now.
     *
     * @param binding The binding.
     * @param running The provider running for it now, or null.
     * @param channelDownForMillis How long its channel has been lost, or null while it is up.
     * @return The provider to run, or null for none.
     */
    fun decide(binding: HubBinding, running: String?, channelDownForMillis: Long?): String? {
        if (!binding.isOverlayWanted || binding.overlays.isEmpty()) return null
        if (running == null) return preferred(binding)?.provider
        if (binding.overlays.none { it.provider == running }) return preferred(binding)?.provider
        val isLost = channelDownForMillis != null && channelDownForMillis > CLIENT_OVERLAY_FAILOVER_S * 1000
        return if (isLost) next(binding, running)?.provider ?: running else running
    }
}
