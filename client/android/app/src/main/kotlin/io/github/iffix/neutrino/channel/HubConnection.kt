package io.github.iffix.neutrino.channel

/** Where one hub's socket stands, by the names every client uses. */
enum class HubConnection {
    /** The hub welcomed this phone and the socket is open. */
    CONNECTED,

    /** A round over the hub's addresses runs, or runs again after a socket closed. */
    CONNECTING,

    /** The last round ended in a code; the next runs after the backoff. */
    DOWN,

    /** Another socket for the same binding took over; nothing runs until a person reconnects. */
    REPLACED,

    /** The hub switched this client off; the socket stays open. */
    DISABLED,
    ;

    /** The name the catalog's `ui.state.<name>` keys and the other clients use. */
    val wireName: String
        get() = name.lowercase()
}
