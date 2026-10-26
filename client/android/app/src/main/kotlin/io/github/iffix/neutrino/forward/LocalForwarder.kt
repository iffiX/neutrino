package io.github.iffix.neutrino.forward

import io.github.iffix.neutrino.channel.ChannelResult
import kotlinx.serialization.json.JsonObject

/** What holds the loopback listeners: each accepted connection a stream on a hub's session. */
interface LocalForwarder {
    /**
     * Listen on `127.0.0.1:<port>` and open a stream with [open] for each connection, or one for a UDP listener.
     *
     * @param bindingId The hub whose session carries the streams.
     * @param port The loopback number, 0 for the system's pick.
     * @param protocol `tcp` or `udp`.
     * @param open The streams' `open` record, `{kind: connect, ...}`.
     * @return The number listened on, or the refusal: `port_taken {port}` when it is held.
     */
    suspend fun start(bindingId: String, port: Int, protocol: String, open: JsonObject): ChannelResult<Int>

    /**
     * Close a listener and its streams.
     *
     * @param port The loopback number.
     * @param protocol `tcp` or `udp`.
     */
    suspend fun stop(port: Int, protocol: String)
}
