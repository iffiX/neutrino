package io.github.iffix.neutrino.terminal

/** Where one terminal tab's shell stands. */
enum class TerminalPhase {
    /** The tab exists and its shell is being opened or attached. */
    CONNECTING,

    /** The shell's stream is open. */
    OPEN,

    /** The stream is gone while the shell may still run: a kept session, or a lost socket. */
    DETACHED,

    /** The shell ended, or the hub refused it. */
    ENDED,
}
