package io.github.iffix.neutrino.channel

import kotlinx.coroutines.channels.SendChannel
import kotlinx.serialization.json.JsonObject

/** How this phone reaches a hub's pinned port: the HTTP calls, and the socket. */
interface HubTransport {
    /**
     * One JSON read from the hub, over a connection checked against the pin before a byte leaves.
     *
     * @param baseUrl The hub's address, `https://host:port`.
     * @param path The route, with its query.
     * @param fingerprint The pinned SHA-256.
     * @return The answer's JSON, or the refusal: the `detail {code, params}` of an error answer,
     *   `hub_untrusted` for another certificate, `hub_unreachable` for anything on the way.
     */
    suspend fun get(baseUrl: String, path: String, fingerprint: String): ChannelResult<JsonObject>

    /**
     * One JSON request to the hub, over a connection checked against the pin before a byte leaves.
     *
     * @param baseUrl The hub's address, `https://host:port`.
     * @param path The route.
     * @param fingerprint The pinned SHA-256.
     * @param body The request body.
     * @return The answer's JSON, or the refusal: the `detail {code, params}` of an error answer,
     *   `hub_untrusted` for another certificate, `hub_unreachable` for anything on the way.
     */
    suspend fun post(baseUrl: String, path: String, fingerprint: String, body: JsonObject): ChannelResult<JsonObject>

    /**
     * Open the socket; what happens on it arrives in [events].
     *
     * @param baseUrl The hub's address, `https://host:port`.
     * @param fingerprint The pinned SHA-256.
     * @param events Where the socket's events go.
     * @return The socket, to send on and close.
     */
    fun connect(baseUrl: String, fingerprint: String, events: SendChannel<ChannelSocketEvent>): ChannelSocket
}
