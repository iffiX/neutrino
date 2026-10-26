package io.github.iffix.neutrino.forward

import io.github.iffix.neutrino.FORWARD_BIND_HOST
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.transport.ClientTransport
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * The loopback listeners the transport holds, started with `forward_start` and closed with `forward_stop`.
 *
 * @param transport The transport's local channel.
 */
class TransportLocalForwarder(private val transport: ClientTransport) : LocalForwarder {
    override suspend fun start(bindingId: String, port: Int, protocol: String, open: JsonObject): ChannelResult<Int> {
        val fields = buildJsonObject {
            put("binding", bindingId)
            put("listen", "$FORWARD_BIND_HOST:$port")
            put("protocol", protocol)
            put("open", open)
        }
        return when (val answer = transport.command("forward_start", fields)) {
            is ChannelResult.Refused -> answer

            is ChannelResult.Ok -> {
                val bound = (answer.value["listen"] as? JsonPrimitive)?.content.orEmpty()
                val number = bound.substringAfterLast(':').toIntOrNull() ?: port
                ChannelResult.Ok(number)
            }
        }
    }

    override suspend fun stop(port: Int, protocol: String) {
        val fields = buildJsonObject {
            put("listen", "$FORWARD_BIND_HOST:$port")
            put("protocol", protocol)
        }
        transport.command("forward_stop", fields)
    }
}
