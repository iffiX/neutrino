package io.github.iffix.neutrino.design

/** The tones a status marker takes. */
enum class DotTone {
    /** Green: connected, on, healthy. */
    OK,

    /** Amber and still: not connected with nothing for a person to do, disabled, unhealthy. */
    WAIT,

    /** Grey: never reached, off. */
    OFF,

    /** Red: a code a person has to act on. */
    BAD,

    /** Amber and pulsing: connecting, or a job running on the row. */
    PULSE,

    /** The amber spinner a button shows while its job runs. */
    SPIN,
}
