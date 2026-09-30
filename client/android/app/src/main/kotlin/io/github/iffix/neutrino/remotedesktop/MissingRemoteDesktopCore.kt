package io.github.iffix.neutrino.remotedesktop

import android.view.Surface
import io.github.iffix.neutrino.channel.ChannelResult

/** The core this build carries: none. Every connection stops at once with `rdp_core_missing`. */
class MissingRemoteDesktopCore : RemoteDesktopCore {
    override fun connect(target: RemoteDesktopTarget, surface: Surface, onState: (RemoteDesktopState) -> Unit) {
        onState(RemoteDesktopState.Stopped(ChannelResult.refused("rdp_core_missing")))
    }

    override fun pointer(x: Int, y: Int, isDown: Boolean) = Unit

    override fun type(text: String) = Unit

    override fun disconnect() = Unit
}
