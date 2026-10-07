package io.github.iffix.neutrino.overlay

/** Where this phone stands on one hub's virtual network. */
enum class OverlayState {
    /** Not on it; the last failure, if any, is kept beside. */
    OFF,

    /** On it: the engine runs and has an address. */
    ON,
    ;

    /** The name the catalog's `ui.overlay.<name>` keys and the other clients use. */
    val wireName: String
        get() = name.lowercase()
}
