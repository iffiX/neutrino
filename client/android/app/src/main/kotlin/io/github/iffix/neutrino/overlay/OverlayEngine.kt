package io.github.iffix.neutrino.overlay

import io.github.iffix.neutrino.channel.ChannelOverlay
import io.github.iffix.neutrino.channel.ChannelResult

/** One virtual network's core, run inside the VPN service. */
interface OverlayEngine {
    /**
     * Join the network on a thread of the engine's own.
     *
     * @param overlay What the hub hands the phone for it.
     * @param tun Where the engine gets its TUN device.
     * @param report Called with each phase, the address with its prefix length once there is one, and the
     *   refusal of a failure.
     */
    fun start(overlay: ChannelOverlay, tun: TunBuilder, report: (OverlayPhase, String, ChannelResult.Refused?) -> Unit)

    /** Leave the network and end the engine's thread. */
    fun stop()
}
