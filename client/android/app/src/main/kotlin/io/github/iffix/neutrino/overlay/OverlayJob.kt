package io.github.iffix.neutrino.overlay

/** What a hub's virtual network button is doing. */
enum class OverlayJob {
    /** Nothing. */
    NONE,

    /** One connect attempt runs, in its `login` stage, then its `hub` stage. */
    CONNECTING,

    /** The engine is being stopped. */
    DISCONNECTING,
}
