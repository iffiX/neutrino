package io.github.iffix.neutrino.channel

/** Where one hub's socket stands. */
enum class HubConnection {
    /** The first round has not finished. */
    CONNECTING,

    /** The hub welcomed this phone and the socket is open. */
    CONNECTED,

    /** The socket is down and a round will run again. */
    RECONNECTING,

    /** Another socket for the same binding took over; nothing runs until a person reconnects. */
    REPLACED,

    /** The hub no longer knows this binding. */
    UNBOUND,
}
