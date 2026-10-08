package io.github.iffix.neutrino.channel

/** Where one hub's socket stands: the three kinds of a hub row's state line. */
enum class HubConnection {
    /** A round over the hub's addresses is dialling. */
    CONNECTING,

    /** The hub welcomed this phone and the socket is open. */
    CONNECTED,

    /** No round is dialling; the view's wait reason names what the row waits for. */
    WAITING,
    ;

    /** The name the catalog's `ui.state.<name>` keys and the other clients use. */
    val wireName: String
        get() = name.lowercase()
}
