package io.github.iffix.neutrino.terminal

import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.ChannelStream
import kotlinx.serialization.json.JsonElement

/** Opens a stream on one hub's live socket. */
fun interface StreamOpener {
    /**
     * Open a stream.
     *
     * @param kind The kind.
     * @param args Its arguments.
     * @param hasBytes Whether it carries bytes.
     * @return The stream, or the refusal.
     */
    fun open(kind: String, args: Map<String, JsonElement>, hasBytes: Boolean): ChannelResult<ChannelStream>
}
