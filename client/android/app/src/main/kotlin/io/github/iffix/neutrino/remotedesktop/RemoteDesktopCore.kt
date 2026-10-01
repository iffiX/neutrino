package io.github.iffix.neutrino.remotedesktop

import android.view.Surface

/**
 * The seam the RustDesk core plugs into: it decodes the machine's screen into a surface and
 * takes the phone's touches and keys. The viewer's chrome is written against this and nothing else.
 */
interface RemoteDesktopCore {
    /**
     * Connect to a shared desktop. Both callbacks run on the main thread.
     *
     * @param target Where it answers, with its seat password.
     * @param onState Called with each change of the connection.
     * @param onFrameSize Called with the remote picture's width and height when they change.
     */
    fun connect(target: RemoteDesktopTarget, onState: (RemoteDesktopState) -> Unit, onFrameSize: (Int, Int) -> Unit)

    /**
     * Draw the picture into this surface from now on.
     *
     * @param surface The surface, or null when it is gone.
     */
    fun attach(surface: Surface?)

    /**
     * A mouse event in the remote picture's pixels.
     *
     * @param event The event.
     */
    fun mouse(event: RemoteDesktopMouse)

    /**
     * A key pressed or released, by RustDesk's name for it.
     *
     * @param code The key's name, such as `VK_ESCAPE`.
     * @param isDown Whether it is pressed.
     */
    fun key(code: String, isDown: Boolean)

    /**
     * Text typed on the phone's keyboard.
     *
     * @param text The text.
     */
    fun type(text: String)

    /** Close the connection. */
    fun disconnect()
}
