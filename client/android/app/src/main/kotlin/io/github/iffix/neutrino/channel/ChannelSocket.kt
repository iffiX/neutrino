package io.github.iffix.neutrino.channel

/** One open socket to a hub, as the session writes to it. */
interface ChannelSocket {
    /**
     * Send one text frame.
     *
     * @param text The frame.
     * @return False when the socket is gone.
     */
    fun sendText(text: String): Boolean

    /**
     * Send one binary frame.
     *
     * @param bytes The frame: the stream id, then the bytes.
     * @return False when the socket is gone.
     */
    fun sendBytes(bytes: ByteArray): Boolean

    /**
     * Send one WebSocket ping; its pong arrives as [ChannelSocketEvent.Pong] with the round trip.
     *
     * @return False when the socket is gone or cannot ping.
     */
    fun ping(): Boolean

    /**
     * Close the socket from this side.
     *
     * @param code The close code.
     * @param reason The close reason.
     */
    fun close(code: Int, reason: String)
}
