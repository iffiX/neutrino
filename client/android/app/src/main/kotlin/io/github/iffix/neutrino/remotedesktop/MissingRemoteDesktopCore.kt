package io.github.iffix.neutrino.remotedesktop

import android.view.Surface
import io.github.iffix.neutrino.channel.ChannelResult

/** The core when this build carries none: every connection stops at once with `rdp_core_missing`. */
class MissingRemoteDesktopCore : RemoteDesktopCore {
    override fun connect(
        target: RemoteDesktopTarget,
        onState: (RemoteDesktopState) -> Unit,
        onFrameSize: (Int, Int) -> Unit,
    ) {
        onState(RemoteDesktopState.Stopped(ChannelResult.refused("rdp_core_missing")))
    }

    override fun attach(surface: Surface?) = Unit

    override fun mouse(event: RemoteDesktopMouse) = Unit

    override fun key(code: String, isDown: Boolean) = Unit

    override fun type(text: String) = Unit

    override fun disconnect() = Unit
}
