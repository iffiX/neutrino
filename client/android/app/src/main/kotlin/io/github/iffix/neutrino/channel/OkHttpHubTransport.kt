package io.github.iffix.neutrino.channel

import io.github.iffix.neutrino.CLIENT_CHANNEL_WS_PATH
import io.github.iffix.neutrino.CLIENT_CONNECT_TIMEOUT_S
import io.github.iffix.neutrino.CLIENT_REQUEST_TIMEOUT_S
import io.github.iffix.neutrino.CLIENT_WS_SILENCE_TIMEOUT_S
import io.github.iffix.neutrino.HubUntrustedException
import java.io.IOException
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLPeerUnverifiedException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.SendChannel
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import okhttp3.ConnectionSpec
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.TlsVersion
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString

/** The pinned transport over OkHttp: TLS 1.2 and up, trusting the one fingerprint and nothing else. */
class OkHttpHubTransport : HubTransport {
    private val clients = ConcurrentHashMap<String, OkHttpClient>()
    private val json = Json { ignoreUnknownKeys = true }

    override suspend fun post(
        baseUrl: String,
        path: String,
        fingerprint: String,
        body: JsonObject,
    ): ChannelResult<JsonObject> = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url(baseUrl.trimEnd('/') + path)
            .post(body.toString().toRequestBody(JSON_TYPE))
            .build()
        try {
            client(fingerprint).newCall(request).execute().use { answer(it) }
        } catch (error: IOException) {
            refusalOf(error, baseUrl)
        } catch (error: IllegalArgumentException) {
            ChannelResult.refused("hub_unreachable", "detail" to (error.message ?: "bad address"))
        }
    }

    override fun connect(baseUrl: String, fingerprint: String, events: SendChannel<ChannelSocketEvent>): ChannelSocket {
        val request = Request.Builder().url(baseUrl.trimEnd('/') + CLIENT_CHANNEL_WS_PATH).build()
        val socket = client(fingerprint).newWebSocket(request, EventListener(events, baseUrl))
        return object : ChannelSocket {
            override fun sendText(text: String): Boolean = socket.send(text)

            override fun sendBytes(bytes: ByteArray): Boolean = socket.send(bytes.toByteString())

            override fun close(code: Int, reason: String) {
                if (!socket.close(code, reason)) socket.cancel()
            }
        }
    }

    private fun client(fingerprint: String): OkHttpClient = clients.getOrPut(fingerprint) {
        val trust = FingerprintTrustManager(fingerprint)
        val context = SSLContext.getInstance("TLS").apply { init(null, arrayOf(trust), null) }
        val spec = ConnectionSpec.Builder(ConnectionSpec.MODERN_TLS)
            .tlsVersions(TlsVersion.TLS_1_3, TlsVersion.TLS_1_2)
            .build()
        OkHttpClient.Builder()
            .sslSocketFactory(context.socketFactory, trust)
            .hostnameVerifier { _, session ->
                val presented = session.peerCertificates.firstOrNull()?.encoded
                presented != null && FingerprintTrustManager.fingerprintOf(presented) == fingerprint
            }
            .connectionSpecs(listOf(spec))
            .connectTimeout(CLIENT_CONNECT_TIMEOUT_S, TimeUnit.SECONDS)
            .readTimeout(CLIENT_WS_SILENCE_TIMEOUT_S, TimeUnit.SECONDS)
            .callTimeout(CLIENT_REQUEST_TIMEOUT_S, TimeUnit.SECONDS)
            .retryOnConnectionFailure(false)
            .build()
    }

    private fun answer(response: Response): ChannelResult<JsonObject> {
        val text = response.body.string()
        val document = try {
            json.parseToJsonElement(text) as? JsonObject
        } catch (_: SerializationException) {
            null
        } ?: JsonObject(emptyMap())
        if (response.isSuccessful) return ChannelResult.Ok(document)
        val detail = document["detail"] as? JsonObject
        val code = (detail?.get("code") as? JsonPrimitive)?.content.orEmpty()
        if (code.isNotEmpty()) {
            return ChannelResult.Refused(code, detail?.get("params") as? JsonObject ?: JsonObject(emptyMap()))
        }
        return if (response.code == 401 || response.code == 403) {
            ChannelResult.refused("hub_refused")
        } else {
            ChannelResult.refused("hub_unreachable", "detail" to "the hub answered ${response.code}")
        }
    }

    private class EventListener(private val events: SendChannel<ChannelSocketEvent>, private val baseUrl: String) :
        WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            events.trySend(ChannelSocketEvent.Opened)
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            events.trySend(ChannelSocketEvent.Text(text))
        }

        override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
            events.trySend(ChannelSocketEvent.Binary(bytes.toByteArray()))
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            webSocket.close(code, null)
            events.trySend(ChannelSocketEvent.Closed(code, reason))
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            events.trySend(ChannelSocketEvent.Closed(code, reason))
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            events.trySend(ChannelSocketEvent.Failed(refusalOf(t, baseUrl)))
        }
    }

    private companion object {
        val JSON_TYPE = "application/json".toMediaType()

        fun refusalOf(error: Throwable, baseUrl: String): ChannelResult.Refused {
            var cause: Throwable? = error
            while (cause != null) {
                if (cause is HubUntrustedException || cause is SSLPeerUnverifiedException) {
                    return ChannelResult.refused("hub_untrusted", "url" to baseUrl)
                }
                cause = cause.cause
            }
            return ChannelResult.refused("hub_unreachable", "detail" to (error.message ?: error.javaClass.simpleName))
        }
    }
}
