package io.github.iffix.neutrino.overlay

/** What a hub's virtual network button is doing. */
enum class OverlayJob {
    /** Nothing. */
    NONE,

    /** One connect attempt runs, for at most 60 s. */
    CONNECTING,

    /** The engine is being stopped. */
    DISCONNECTING,
}
