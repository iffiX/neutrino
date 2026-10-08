package io.github.iffix.neutrino.channel

/** What happens on a socket, in the order it happens. */
sealed interface ChannelSocketEvent {
    /** The upgrade finished: the pin checked out and frames may be sent. */
    data object Opened : ChannelSocketEvent

    /**
     * A text frame arrived.
     *
     * @property text The frame.
     */
    data class Text(val text: String) : ChannelSocketEvent

    /**
     * A binary frame arrived.
     *
     * @property bytes The frame: the stream id, then the bytes.
     */
    class Binary(val bytes: ByteArray) : ChannelSocketEvent

    /**
     * The hub closed the socket.
     *
     * @property code The close code.
     * @property reason The close reason.
     */
    data class Closed(val code: Int, val reason: String) : ChannelSocketEvent

    /**
     * The socket failed: it did not open, the pin did not match, or the wire broke.
     *
     * @property refusal `hub_untrusted` for a certificate that is not the pinned one, a refusal
     *   the upgrade's answer carried, else `hub_unreachable`.
     */
    data class Failed(val refusal: ChannelResult.Refused) : ChannelSocketEvent
}
