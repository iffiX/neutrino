package io.github.iffix.neutrino.overlay

import io.github.iffix.neutrino.CLIENT_ADDRESS_SCHEME
import io.github.iffix.neutrino.CLIENT_AGENT_PORT_DEFAULT
import io.github.iffix.neutrino.OVERLAY_NETBIRD_NETWORK
import io.github.iffix.neutrino.OVERLAY_PROVIDER_NETBIRD
import io.github.iffix.neutrino.binding.HubBinding
import io.github.iffix.neutrino.channel.ChannelOverlay
import java.net.URI
import java.net.URISyntaxException

/** Which of a hub's virtual networks a connect joins, and where the hub answers on it. */
object OverlayChoice {
    private val ipv4 = Regex("""\d{1,3}(\.\d{1,3}){3}""")

    /**
     * The network a hub's binding names.
     *
     * @param binding The binding.
     * @return The picked network while the hub still publishes it, else the hub's first, else null.
     */
    fun preferred(binding: HubBinding): ChannelOverlay? =
        binding.overlays.firstOrNull { it.provider == binding.overlayChoice } ?: binding.overlays.firstOrNull()

    /**
     * The hub's channel address on one of its networks: the hub's own address on it as the
     * material names it, never the hub's name there; else an address of the hub's list whose
     * host is an IP inside the network (NetBird's 100.64.0.0/10, or the EasyTier network this
     * phone is on). An address of the hub's list on the chosen host is taken as it is; otherwise
     * the host takes the port the binding last answered on.
     *
     * @param binding The binding.
     * @param overlay The network.
     * @param address This phone's address on the network, empty when not known.
     * @param prefix The network's prefix length around [address].
     * @return The address, or empty when nothing names the hub on the network.
     */
    fun hubUrl(binding: HubBinding, overlay: ChannelOverlay, address: String = "", prefix: Int = 0): String {
        if (overlay.hubAddress.isNotEmpty()) return urlOn(binding, overlay.hubAddress)
        val (network, length) = if (overlay.provider == OVERLAY_PROVIDER_NETBIRD) {
            OVERLAY_NETBIRD_NETWORK.split('/').let { it[0] to it[1].toInt() }
        } else {
            address to prefix
        }
        return binding.storedUrls.firstOrNull { isInside(hostOf(it), network, length) }.orEmpty()
    }

    private fun urlOn(binding: HubBinding, host: String): String {
        binding.storedUrls.firstOrNull { hostOf(it) == host }?.let { return it }
        val port = portOf(binding.gatewayUrl)
        val bracketed = if (':' in host) "[$host]" else host
        return "$CLIENT_ADDRESS_SCHEME://$bracketed:$port"
    }

    private fun isInside(host: String, network: String, length: Int): Boolean {
        if (length !in 1..32 || !ipv4.matches(host) || !ipv4.matches(network)) return false
        val mask = (0xffffffffL shl (32 - length)) and 0xffffffffL
        return (valueOf(host) and mask) == (valueOf(network) and mask)
    }

    private fun valueOf(address: String): Long {
        var value = 0L
        for (part in address.split('.')) value = value * 256 + part.toLong()
        return value
    }

    private fun hostOf(url: String): String = try {
        URI(url).host.orEmpty().removePrefix("[").removeSuffix("]")
    } catch (_: URISyntaxException) {
        ""
    }

    private fun portOf(url: String): Int = try {
        URI(url).port.takeIf { it > 0 } ?: CLIENT_AGENT_PORT_DEFAULT
    } catch (_: URISyntaxException) {
        CLIENT_AGENT_PORT_DEFAULT
    }
}
