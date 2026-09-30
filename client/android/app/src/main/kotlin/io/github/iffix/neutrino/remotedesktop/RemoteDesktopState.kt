package io.github.iffix.neutrino.remotedesktop

import io.github.iffix.neutrino.channel.ChannelResult

/** Where a viewer's connection stands. */
sealed interface RemoteDesktopState {
    /** The core is reaching the machine. */
    data object Connecting : RemoteDesktopState

    /** The core draws the machine's screen into the surface. */
    data object Showing : RemoteDesktopState

    /**
     * The viewer shows no picture.
     *
     * @property refusal Why: the core's refusal, or `rdp_core_missing` while no core is built in.
     */
    data class Stopped(val refusal: ChannelResult.Refused) : RemoteDesktopState
}
