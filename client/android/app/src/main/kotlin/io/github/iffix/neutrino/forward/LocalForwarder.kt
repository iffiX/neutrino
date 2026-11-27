package io.github.iffix.neutrino.forward

import io.github.iffix.neutrino.channel.ChannelResult
import kotlinx.serialization.json.JsonObject

/** What holds the loopback listeners: each accepted connection a stream on a hub's session. */
interface LocalForwarder {
    /**
     * Listen on `127.0.0.1:<port>`, and on `[::1]` at the same number for a forward a browser opens, and open a
     * stream with [open] for each connection, or one for a UDP listener.
     *
     * @param bindingId The hub whose session carries the streams.
     * @param port The loopback number, 0 for the system's pick.
     * @param protocol `tcp` or `udp`.
     * @param open The streams' `open` record, `{kind: connect, ...}`.
     * @param isBrowserOpened Whether a browser opens the forward, which then also listens on `[::1]`.
     * @return The number listened on, or the refusal: `port_taken {port}` when either address holds it.
     */
    suspend fun start(
        bindingId: String,
        port: Int,
        protocol: String,
        open: JsonObject,
        isBrowserOpened: Boolean,
    ): ChannelResult<Int>

    /**
     * Close a forward's listeners and their streams.
     *
     * @param port The loopback number.
     * @param protocol `tcp` or `udp`.
     * @param isBrowserOpened Whether the forward also listens on `[::1]`.
     */
    suspend fun stop(port: Int, protocol: String, isBrowserOpened: Boolean)
}
