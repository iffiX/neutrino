package io.github.iffix.neutrino.overlay

import io.github.iffix.neutrino.CLIENT_HTTPS_DEFAULT_PORT
import io.github.iffix.neutrino.Edition
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
     * material names it; else an address of the hub's list whose host is an IP inside the
     * network (the network a left-out feature's part names, or the one this phone is on); else
     * the hub's name the part gives. An address of the hub's list on the chosen host is taken as it is;
     * otherwise the host takes the port the binding last answered on.
     *
     * @param binding The binding.
     * @param overlay The network.
     * @param address This phone's address on the network, empty when not known.
     * @param prefix The network's prefix length around [address].
     * @return The address, or empty when nothing names the hub on the network.
     */
    fun hubUrl(binding: HubBinding, overlay: ChannelOverlay, address: String = "", prefix: Int = 0): String {
        if (overlay.hubAddress.isNotEmpty()) return urlOn(binding, overlay.hubAddress)
        val part = Edition.overlayPart(overlay.provider)
        val (network, length) = part?.hubNetwork?.split('/')?.let { it[0] to it[1].toInt() } ?: (address to prefix)
        binding.storedUrls.firstOrNull { isInside(hostOf(it), network, length) }?.let { return it }
        val name = part?.hubName(overlay).orEmpty()
        return if (name.isNotEmpty()) urlOn(binding, name) else ""
    }

    private fun urlOn(binding: HubBinding, host: String): String {
        binding.storedUrls.firstOrNull { hostOf(it) == host }?.let { return it }
        val port = portOf(binding.gatewayUrl)
        val bracketed = if (':' in host) "[$host]" else host
        return "https://$bracketed:$port"
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
        URI(url).port.takeIf { it > 0 } ?: CLIENT_HTTPS_DEFAULT_PORT
    } catch (_: URISyntaxException) {
        CLIENT_HTTPS_DEFAULT_PORT
    }
}
