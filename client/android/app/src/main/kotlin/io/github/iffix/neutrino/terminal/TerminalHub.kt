package io.github.iffix.neutrino.terminal

import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.transport.TransportStream
import kotlinx.serialization.json.JsonObject

/** What a terminal tab asks of one hub while it is connected. */
interface TerminalHub {
    /**
     * Open a `shell` stream; blocks until the hub answers.
     *
     * @param open The stream's `open` record.
     * @return The stream, or the refusal.
     */
    fun open(open: JsonObject): ChannelResult<TransportStream>

    /**
     * Set whether a kept shell stays and whether others can attach to it.
     *
     * @param sessionId The session.
     * @param isPersistent Whether it outlives every window.
     * @param isShared Whether every client with terminal rights on the machine lists it.
     * @return The reply, or its refusal.
     */
    suspend fun persist(sessionId: String, isPersistent: Boolean, isShared: Boolean): ChannelResult<JsonObject>

    /**
     * End a kept shell.
     *
     * @param sessionId The session.
     * @return The reply, or its refusal.
     */
    suspend fun stopSession(sessionId: String): ChannelResult<JsonObject>
}
