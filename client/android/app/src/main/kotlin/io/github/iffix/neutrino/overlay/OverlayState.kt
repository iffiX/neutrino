package io.github.iffix.neutrino.overlay

/** Where this phone stands on one hub's virtual network. */
enum class OverlayState {
    /** Not on it; the last failure, if any, is kept beside. */
    OFF,

    /** One attempt runs: the engine starts, takes an address, and the channel comes up through it. */
    CONNECTING,

    /** On it, with an address, and the hub's channel up through it. */
    ON,
    ;

    /** The name the catalog's `ui.overlay.<name>` keys and the other clients use. */
    val wireName: String
        get() = name.lowercase()
}
