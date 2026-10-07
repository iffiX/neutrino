package io.github.iffix.neutrino.channel

import kotlinx.coroutines.channels.SendChannel
import kotlinx.serialization.json.JsonObject

/**
 * A hub on the other end of the pin, played by the test.
 *
 * @param onConnect What the hub does when an address is dialled: the events it queues at once.
 */
class FakeHubTransport(private val onConnect: (String) -> List<ChannelSocketEvent>) : HubTransport {
    /** Every socket dialled, with its address and its event channel, in order. */
    val dialled = mutableListOf<Triple<String, FakeChannelSocket, SendChannel<ChannelSocketEvent>>>()

    /** What each POST answers, by address and path. */
    val answers = mutableMapOf<Pair<String, String>, ChannelResult<JsonObject>>()

    /** Every POST sent, as address, path and body. */
    val posts = mutableListOf<Triple<String, String, JsonObject>>()

    override suspend fun post(
        baseUrl: String,
        path: String,
        fingerprint: String,
        body: JsonObject,
    ): ChannelResult<JsonObject> {
        posts += Triple(baseUrl, path, body)
        return answers[baseUrl to path] ?: ChannelResult.refused("hub_unreachable", "detail" to "refused")
    }

    /**
     * The round's socket: the last one dialled that a hello was sent on.
     *
     * @return Its address, socket and event channel.
     */
    fun greeted(): Triple<String, FakeChannelSocket, SendChannel<ChannelSocketEvent>> =
        dialled.last { it.second.sent("hello").isNotEmpty() }

    override fun connect(baseUrl: String, fingerprint: String, events: SendChannel<ChannelSocketEvent>): ChannelSocket {
        val socket = FakeChannelSocket()
        dialled += Triple(baseUrl, socket, events)
        onConnect(baseUrl).forEach { events.trySend(it) }
        return socket
    }

    companion object {
        /** The events of a hub that welcomes. */
        val welcoming: List<ChannelSocketEvent> = listOf(
            ChannelSocketEvent.Opened,
            ChannelSocketEvent.Text(
                """{"type":"welcome","protocol":3,"role":"hub","id":"hub-1","name":"Neutrino","software":"neutrino_hub/0.5.0"}""",
            ),
        )

        /**
         * The events of a hub that refuses the hello.
         *
         * @param code The refusal's code.
         * @return The events.
         */
        fun refusing(code: String): List<ChannelSocketEvent> = listOf(
            ChannelSocketEvent.Opened,
            ChannelSocketEvent.Text("""{"type":"refused","code":"$code","params":{}}"""),
            ChannelSocketEvent.Closed(4000, ""),
        )

        /** The events of an address whose connect never ends: none. */
        val hanging: List<ChannelSocketEvent> = emptyList()

        /** The events of an address nothing answers on. */
        val silent: List<ChannelSocketEvent> =
            listOf(ChannelSocketEvent.Failed(ChannelResult.refused("hub_unreachable", "detail" to "timed out")))

        /** The events of an address another certificate answers on. */
        val impostor: List<ChannelSocketEvent> =
            listOf(ChannelSocketEvent.Failed(ChannelResult.refused("hub_untrusted", "url" to "x")))
    }
}
