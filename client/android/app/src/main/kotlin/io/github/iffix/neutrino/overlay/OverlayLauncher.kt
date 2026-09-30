package io.github.iffix.neutrino.overlay

/** Starts and stops the VPN service's one network. */
interface OverlayLauncher {
    /**
     * Run one hub's network, leaving whatever ran before.
     *
     * @param bindingId The hub.
     * @param provider The network's provider.
     */
    fun start(bindingId: String, provider: String)

    /** Leave the network. */
    fun stop()
}
