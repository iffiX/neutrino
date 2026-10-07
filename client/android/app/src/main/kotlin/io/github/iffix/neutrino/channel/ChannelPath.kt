package io.github.iffix.neutrino.channel

import java.net.InetAddress
import java.net.NetworkInterface
import java.net.SocketException
import java.net.URI
import java.net.URISyntaxException
import java.net.UnknownHostException

/**
 * The way a candidate address reaches a hub, known before its hello, with the rank a round on a
 * connected hub compares: `lan`, then `direct`, then the virtual networks, then the relay.
 *
 * @property wireName The hub's word for the path, as `reached_through` names it.
 * @property rank The path's place, 1 the best.
 */
enum class ChannelPath(val wireName: String, val rank: Int) {
    /** An address inside a network this phone holds an address in. */
    LAN("lan", 1),

    /** Any other address of the hub's. */
    DIRECT("direct", 2),

    /** The hub's address on its NetBird network. */
    NETBIRD("netbird", 3),

    /** The hub's address on its EasyTier network. */
    EASYTIER("easytier", 3),

    /** The relay's address the hub's state names. */
    RELAY("relay", 4),
    ;

    companion object {
        /**
         * The path of one candidate address.
         *
         * @param url The address, `https://host:port`.
         * @param overlay The virtual network that is on, or null.
         * @param relayUrl The relay's address from the hub's last state, empty when it names none.
         * @param localNetworks The networks this phone holds an address in.
         * @return The path: the network's engine for the hub's address on it or an address inside
         *   it, the relay for the relay's address, `lan` inside a local network, else `direct`.
         */
        fun of(
            url: String,
            overlay: ChannelOverlayRoute?,
            relayUrl: String,
            localNetworks: List<ChannelLocalNetwork>,
        ): ChannelPath {
            val host = literalHostOf(url)
            if (overlay != null && (url == overlay.url || (host != null && overlay.network?.holds(host) == true))) {
                return ofEngine(overlay.provider)
            }
            if (relayUrl.isNotEmpty() && url == relayUrl) return RELAY
            if (host != null && localNetworks.any { it.holds(host) }) return LAN
            return DIRECT
        }

        /**
         * The path of a virtual network's engine.
         *
         * @param provider `netbird` or `easytier`.
         * @return The engine's path; `direct` for an engine with no path of its own.
         */
        fun ofEngine(provider: String): ChannelPath = entries.firstOrNull { it.wireName == provider } ?: DIRECT

        /**
         * The networks the phone's interfaces that are up hold an address in, loopback aside.
         *
         * @return Each interface address with its prefix length; empty when the interfaces cannot be read.
         */
        fun deviceNetworks(): List<ChannelLocalNetwork> = try {
            NetworkInterface.getNetworkInterfaces()?.toList().orEmpty()
                .filter { it.isUp && !it.isLoopback }
                .flatMap { it.interfaceAddresses }
                .mapNotNull { held -> held.address?.let { ChannelLocalNetwork(it, held.networkPrefixLength.toInt()) } }
        } catch (_: SocketException) {
            emptyList()
        }

        private fun literalHostOf(url: String): InetAddress? {
            val host = try {
                URI(url).host
            } catch (_: URISyntaxException) {
                null
            }?.removePrefix("[")?.removeSuffix("]") ?: return null
            if (!host.contains(':') && !IPV4.matches(host)) return null
            return try {
                InetAddress.getByName(host)
            } catch (_: UnknownHostException) {
                null
            }
        }

        private val IPV4 = Regex("""\d{1,3}(\.\d{1,3}){3}""")
    }
}
