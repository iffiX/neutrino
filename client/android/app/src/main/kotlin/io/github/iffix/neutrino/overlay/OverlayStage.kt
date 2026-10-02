package io.github.iffix.neutrino.overlay

/** Which of a connect's two stages runs, each with its own limit. */
enum class OverlayStage {
    /** No connect runs. */
    NONE,

    /** The engine starts, logs in and gets an address; at most 90 s, or no limit once a console holds the phone. */
    LOGIN,

    /** The hub answers at its address on the network and the channel runs through it; no limit. */
    HUB,
    ;

    /** The name the other clients use: empty, `login` or `hub`. */
    val wireName: String
        get() = if (this == NONE) "" else name.lowercase()
}
