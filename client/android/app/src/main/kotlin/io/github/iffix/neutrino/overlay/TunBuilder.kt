package io.github.iffix.neutrino.overlay

/** Makes the phone's one TUN device for an engine, and keeps an engine's own sockets off it. */
interface TunBuilder {
    /**
     * Build the TUN device.
     *
     * @param address This phone's address on the network.
     * @param prefix Its prefix length.
     * @param mtu The device's MTU.
     * @param routes The networks routed into it, as `address/prefix`.
     * @param dnsServers The resolvers the phone asks while it is up.
     * @param searchDomains The domains a bare name is tried in.
     * @param isHandedOver Whether the engine takes the descriptor and closes it itself.
     * @return The device's descriptor, or null when the phone refused it.
     */
    fun establish(
        address: String,
        prefix: Int,
        mtu: Int,
        routes: List<String>,
        dnsServers: List<String>,
        searchDomains: List<String>,
        isHandedOver: Boolean,
    ): Int?

    /**
     * Keep one socket of the engine's off the TUN device.
     *
     * @param fd The socket.
     * @return Whether it was kept off.
     */
    fun protect(fd: Int): Boolean

    /** Close a device this builder still holds. */
    fun close()
}
