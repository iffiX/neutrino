package io.github.iffix.neutrino.channel

import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class OkHttpHubTransportTest {
    private val held = HeldCertificate.Builder().commonName("hub").ecdsa256().build()
    private val server = MockWebServer().apply {
        useHttps(HandshakeCertificates.Builder().heldCertificate(held).build().sslSocketFactory(), false)
        start()
    }
    private val baseUrl = "https://127.0.0.1:${server.port}"
    private val pinned = FingerprintTrustManager.fingerprintOf(held.certificate.encoded)
    private val transport = OkHttpHubTransport()

    @After
    fun stopServer() {
        server.shutdown()
    }

    @Test
    fun aPostOnThePinnedCertificateIsAnswered() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"id":"b","token":"t"}"""))
        val answer = transport.post(baseUrl, "/api/channel/join", pinned, JsonObject(emptyMap()))
        assertEquals("t", (answer as ChannelResult.Ok).value["token"]!!.jsonPrimitive.content)
        assertEquals("/api/channel/join", server.takeRequest().path)
    }

    @Test
    fun anotherCertificateIsUntrustedAndNothingIsSent() = runBlocking {
        server.enqueue(MockResponse().setBody("{}"))
        val answer = transport.post(baseUrl, "/api/channel/join", "00".repeat(32), JsonObject(emptyMap()))
        assertEquals("hub_untrusted", (answer as ChannelResult.Refused).code)
        assertEquals(0, server.requestCount)
    }

    @Test
    fun anErrorAnswersDetailIsTheRefusal() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(409)
                .setBody("""{"detail":{"code":"protocol_too_old","params":{"peer":2,"hub":3,"min":3}}}"""),
        )
        val answer = transport.post(baseUrl, "/api/channel/join", pinned, JsonObject(emptyMap()))
        assertEquals("protocol_too_old", (answer as ChannelResult.Refused).code)
        assertEquals("3", answer.wordParams["min"])
    }

    @Test
    fun nothingListeningIsUnreachable() = runBlocking {
        val answer = transport.post("https://127.0.0.1:1", "/api/channel/join", pinned, JsonObject(emptyMap()))
        assertEquals("hub_unreachable", (answer as ChannelResult.Refused).code)
    }

    @Test
    fun theSocketOpensOnThePinAndCarriesText() = runBlocking {
        server.enqueue(
            MockResponse().withWebSocketUpgrade(
                object : WebSocketListener() {
                    override fun onOpen(webSocket: WebSocket, response: Response) {
                        webSocket.send("""{"type":"welcome"}""")
                    }
                },
            ),
        )
        val events = Channel<ChannelSocketEvent>(Channel.UNLIMITED)
        transport.connect(baseUrl, pinned, events)
        withTimeout(10_000) {
            assertEquals(ChannelSocketEvent.Opened, events.receive())
            assertEquals(ChannelSocketEvent.Text("""{"type":"welcome"}"""), events.receive())
        }
        assertEquals("/api/channel/socket", server.takeRequest().path)
    }

    @Test
    fun eachPingsPongArrivesWithItsRoundTrip() = runBlocking {
        server.enqueue(
            MockResponse().withWebSocketUpgrade(
                object : WebSocketListener() {
                    override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                        webSocket.close(code, null)
                    }
                },
            ),
        )
        val events = Channel<ChannelSocketEvent>(Channel.UNLIMITED)
        val socket = transport.connect(baseUrl, pinned, events)
        withTimeout(30_000) {
            assertEquals(ChannelSocketEvent.Opened, events.receive())
            repeat(2) {
                assertEquals(true, socket.ping())
                val pong = events.receive() as ChannelSocketEvent.Pong
                assertTrue(pong.rttMillis in 0..29_999)
            }
            socket.close(1000, "")
            assertEquals(ChannelSocketEvent.Closed(1000, ""), events.receive())
        }
    }

    @Test
    fun theSocketOnAnotherCertificateFailsUntrusted() = runBlocking {
        val events = Channel<ChannelSocketEvent>(Channel.UNLIMITED)
        transport.connect(baseUrl, "00".repeat(32), events)
        val event = withTimeout(10_000) { events.receive() }
        assertEquals("hub_untrusted", (event as ChannelSocketEvent.Failed).refusal.code)
    }
}
