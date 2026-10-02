package io.github.iffix.neutrino.overlay

/** Where the phone stands on a hub's virtual network, as the chip draws it. */
enum class OverlayPhase {
    /** Not on it: grey. */
    OFF,

    /** The engine is joining: amber. */
    JOINING,

    /** Registered with a console that has assigned no network yet: amber. */
    WAITING,

    /** On it, with an address: green. */
    ON,

    /** The engine is leaving: amber. */
    LEAVING,

    /** The engine stopped on an error: grey, with the error worded. */
    FAILED,
}
