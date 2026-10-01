package io.github.iffix.neutrino.remotedesktop

/** What the RustDesk core calls back, on its own threads. */
interface RustDeskCallbacks {
    /**
     * The connection changed.
     *
     * @param state One of the `RDP_STATE_` constants.
     * @param text Why it ended, in RustDesk's words; empty otherwise.
     */
    fun onState(state: Int, text: String)

    /**
     * The remote picture has a new size.
     *
     * @param width Its width in pixels.
     * @param height Its height in pixels.
     */
    fun onSize(width: Int, height: Int)
}
