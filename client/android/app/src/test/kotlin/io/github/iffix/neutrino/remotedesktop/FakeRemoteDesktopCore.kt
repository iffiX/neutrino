package io.github.iffix.neutrino.remotedesktop

import android.view.Surface

class FakeRemoteDesktopCore : RemoteDesktopCore {
    val calls = mutableListOf<String>()

    override fun connect(
        target: RemoteDesktopTarget,
        onState: (RemoteDesktopState) -> Unit,
        onFrameSize: (Int, Int) -> Unit,
        onClipboard: (String) -> Unit,
    ) = Unit

    override fun attach(surface: Surface?) = Unit

    override fun mouse(event: RemoteDesktopMouse) = Unit

    override fun key(code: String, isDown: Boolean) {
        calls += "key $code ${if (isDown) "down" else "up"}"
    }

    override fun type(text: String) {
        calls += "text $text"
    }

    override fun clipboard(text: String) {
        calls += "clipboard $text"
    }

    override fun disconnect() = Unit
}
