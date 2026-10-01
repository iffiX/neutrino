package io.github.iffix.neutrino.terminal

/** Where one terminal tab's stream stands. */
enum class TerminalPhase {
    /** A new shell is being opened, or a listed one attached. */
    CONNECTING,

    /** The shell's stream is open. */
    OPEN,

    /** No stream is attached while the session may still run: listed and not yet selected, or a lost socket. */
    DETACHED,

    /** The session is gone from the hub's list, the shell ended, or the hub refused it. */
    ENDED,
}
