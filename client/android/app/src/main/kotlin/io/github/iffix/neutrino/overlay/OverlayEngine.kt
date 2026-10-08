package io.github.iffix.neutrino.overlay

import io.github.iffix.neutrino.channel.ChannelOverlay
import io.github.iffix.neutrino.channel.ChannelResult

/** One virtual network's core, run inside the VPN service. */
interface OverlayEngine {
    /**
     * Join the network on a thread of the engine's own. The VPN service calls it off the main thread.
     *
     * @param overlay What the hub hands the phone for it.
     * @param tun Where the engine gets its TUN device.
     * @param report Called with each phase, the address with its prefix length once there is one, and the
     *   refusal of a failure.
     */
    fun start(overlay: ChannelOverlay, tun: TunBuilder, report: (OverlayPhase, String, ChannelResult.Refused?) -> Unit)

    /**
     * Leave the network and end the engine's thread. The call may block until the core has stopped;
     * the VPN service makes it off the main thread.
     */
    fun stop()
}
