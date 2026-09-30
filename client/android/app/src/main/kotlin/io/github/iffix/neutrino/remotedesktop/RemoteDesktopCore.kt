package io.github.iffix.neutrino.remotedesktop

import android.view.Surface

/**
 * The seam the RustDesk core plugs into: it decodes the machine's screen into a surface and
 * takes the phone's touches and keys. The viewer's chrome is written against this and nothing else.
 */
interface RemoteDesktopCore {
    /**
     * Connect to a shared desktop and draw it.
     *
     * @param target Where it answers, with its seat password.
     * @param surface Where the decoded picture is drawn.
     * @param onState Called with each change of the connection.
     */
    fun connect(target: RemoteDesktopTarget, surface: Surface, onState: (RemoteDesktopState) -> Unit)

    /**
     * A touch on the surface, in the surface's pixels.
     *
     * @param x The horizontal position.
     * @param y The vertical position.
     * @param isDown Whether the finger is down.
     */
    fun pointer(x: Int, y: Int, isDown: Boolean)

    /**
     * Text typed on the phone's keyboard.
     *
     * @param text The text.
     */
    fun type(text: String)

    /** Close the connection. */
    fun disconnect()
}
