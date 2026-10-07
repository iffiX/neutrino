package io.github.iffix.neutrino.overlay

/** Whether a connect's one stage runs. */
enum class OverlayStage {
    /** No connect runs. */
    NONE,

    /** The engine starts, logs in and gets an address; at most 90 s, or no limit once a console holds the phone. */
    LOGIN,
    ;

    /** The name the other clients use: empty or `login`. */
    val wireName: String
        get() = if (this == NONE) "" else name.lowercase()
}
