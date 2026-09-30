package io.github.iffix.neutrino.design

/** The four tones a status marker takes, and the spinner of a step in flight. */
enum class DotTone {
    /** On, running, answering. */
    OK,

    /** Degraded, or waiting on something. */
    WAIT,

    /** Not started, nothing to report. */
    OFF,

    /** Failed, stopped, unreachable. */
    BAD,

    /** A step in flight: joining, leaving, connecting. */
    SPIN,
}
