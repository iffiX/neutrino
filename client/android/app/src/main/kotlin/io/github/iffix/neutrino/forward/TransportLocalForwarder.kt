package io.github.iffix.neutrino.forward

import io.github.iffix.neutrino.FORWARD_BIND_HOST
import io.github.iffix.neutrino.FORWARD_BIND_HOST_IPV6
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
    override suspend fun start(
        bindingId: String,
        port: Int,
        protocol: String,
        open: JsonObject,
        isBrowserOpened: Boolean,
    ): ChannelResult<Int> {
        val number = when (val first = listen(bindingId, FORWARD_BIND_HOST, port, protocol, open)) {
            is ChannelResult.Refused -> return first
            is ChannelResult.Ok -> first.value
        }
        if (!isBrowserOpened) return ChannelResult.Ok(number)
        val second = listen(bindingId, FORWARD_BIND_HOST_IPV6, number, protocol, open)
        if (second is ChannelResult.Refused) {
            close(FORWARD_BIND_HOST, number, protocol)
            return second
        }
        return ChannelResult.Ok(number)
    }

    override suspend fun stop(port: Int, protocol: String, isBrowserOpened: Boolean) {
        close(FORWARD_BIND_HOST, port, protocol)
        if (isBrowserOpened) close(FORWARD_BIND_HOST_IPV6, port, protocol)
    }

    private suspend fun listen(
        bindingId: String,
        host: String,
        port: Int,
        protocol: String,
        open: JsonObject,
    ): ChannelResult<Int> {
        val fields = buildJsonObject {
            put("binding", bindingId)
            put("listen", "$host:$port")
            put("protocol", protocol)
            put("open", open)
        }
        return when (val answer = transport.command("forward_start", fields)) {
            is ChannelResult.Refused -> answer

            is ChannelResult.Ok -> {
                val bound = (answer.value["listen"] as? JsonPrimitive)?.content.orEmpty()
                ChannelResult.Ok(bound.substringAfterLast(':').toIntOrNull() ?: port)
            }
        }
    }

    private suspend fun close(host: String, port: Int, protocol: String) {
        val fields = buildJsonObject {
            put("listen", "$host:$port")
            put("protocol", protocol)
        }
        transport.command("forward_stop", fields)
    }
}
