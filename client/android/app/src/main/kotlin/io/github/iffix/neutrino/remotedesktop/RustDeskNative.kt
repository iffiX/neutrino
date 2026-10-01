package io.github.iffix.neutrino.remotedesktop

import android.view.Surface

/**
 * The RustDesk core's C interface, reached through `libneutrino_rustdesk.so` (`src/main/cpp`).
 * `librustdesk.so` is built by `packaging/mobile_rustdesk.py`; a build without it has [isLoaded]
 * false.
 */
object RustDeskNative {
    /** Whether the core and its JNI side loaded and the core exports every call. */
    val isLoaded: Boolean by lazy(::load)

    /**
     * Find the core's calls in the loaded `librustdesk.so`.
     *
     * @return Whether every call was found.
     */
    external fun open(): Boolean

    /**
     * Set where the core keeps its configuration. Call once.
     *
     * @param appDir A directory of the app's own.
     */
    external fun init(appDir: String)

    /**
     * Connect straight to a machine's RustDesk.
     *
     * @param peer The machine's address.
     * @param port Its direct port.
     * @param password Its seat password.
     * @param callbacks What the core reports to.
     * @return 0, or -1 while another session runs.
     */
    external fun start(peer: String, port: Int, password: String, callbacks: RustDeskCallbacks): Int

    /**
     * Draw into this surface, or into nothing.
     *
     * @param surface The surface, or null.
     */
    external fun attach(surface: Surface?)

    /**
     * A mouse event.
     *
     * @param x The column, or the horizontal wheel steps.
     * @param y The row, or the vertical wheel steps.
     * @param mask The type and the buttons.
     */
    external fun mouse(x: Int, y: Int, mask: Int)

    /**
     * A key by RustDesk's name.
     *
     * @param code The name.
     * @param isDown Whether it is pressed.
     */
    external fun key(code: String, isDown: Boolean)

    /**
     * Typed text.
     *
     * @param utf8 The text in UTF-8.
     */
    external fun text(utf8: ByteArray)

    /** End the session; no callback runs after this returns. */
    external fun close()

    private fun load(): Boolean = try {
        System.loadLibrary("c++_shared")
        System.loadLibrary("rustdesk")
        System.loadLibrary("neutrino_rustdesk")
        open()
    } catch (_: UnsatisfiedLinkError) {
        false
    }
}
