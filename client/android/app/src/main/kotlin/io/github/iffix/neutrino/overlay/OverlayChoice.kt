package io.github.iffix.neutrino.overlay

import io.github.iffix.neutrino.CLIENT_HTTPS_DEFAULT_PORT
import io.github.iffix.neutrino.OVERLAY_PROVIDER_NETBIRD
import io.github.iffix.neutrino.binding.HubBinding
import io.github.iffix.neutrino.channel.ChannelOverlay
import java.net.URI
import java.net.URISyntaxException

/** Which of a hub's virtual networks a connect joins, and where the hub answers on it. */
object OverlayChoice {
    /**
     * The network a hub's binding names.
     *
     * @param binding The binding.
     * @return The picked network while the hub still publishes it, else the hub's first, else null.
     */
    fun preferred(binding: HubBinding): ChannelOverlay? =
        binding.overlays.firstOrNull { it.provider == binding.overlayChoice } ?: binding.overlays.firstOrNull()

    /**
     * The hub's channel address on one of its networks: the address of the hub's list on that
     * host, else that host at the port the binding last answered on.
     *
     * @param binding The binding.
     * @param overlay The network.
     * @return The address, or empty when the hub names no address of its own on the network.
     */
    fun hubUrl(binding: HubBinding, overlay: ChannelOverlay): String {
        val host = if (overlay.provider == OVERLAY_PROVIDER_NETBIRD) overlay.fqdn else overlay.hubAddress
        if (host.isEmpty()) return ""
        binding.storedUrls.firstOrNull { hostOf(it) == host }?.let { return it }
        val port = portOf(binding.gatewayUrl)
        val bracketed = if (':' in host) "[$host]" else host
        return "https://$bracketed:$port"
    }

    private fun hostOf(url: String): String = try {
        URI(url).host.orEmpty().removePrefix("[").removeSuffix("]")
    } catch (_: URISyntaxException) {
        ""
    }

    private fun portOf(url: String): Int = try {
        URI(url).port.takeIf { it > 0 } ?: CLIENT_HTTPS_DEFAULT_PORT
    } catch (_: URISyntaxException) {
        CLIENT_HTTPS_DEFAULT_PORT
    }
}
