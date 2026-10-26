package io.github.iffix.neutrino.forward

import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.transport.ClientTransport
import io.github.iffix.neutrino.transport.FakeTransport
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Test

class TransportLocalForwarderTest {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val fake = FakeTransport()
    private val forwarder =
        TransportLocalForwarder(ClientTransport(fake, "/data", { fake }, scope, log = {}).also { it.start() })
    private val open = buildJsonObject {
        put("kind", "connect")
        put("id", "gitea_d1_web")
    }

    @After
    fun end() {
        scope.cancel()
    }

    @Test
    fun aForwardListensOnTheLoopbackAtItsNumberAndAnswersTheAddressBound() {
        fake.answer = { buildJsonObject { put("listen", "127.0.0.1:27311") } }
        assertEquals(ChannelResult.Ok(27311), runBlocking { forwarder.start("b1", 27311, "tcp", open) })
        val start = fake.nextCommand("forward_start") ?: error("no forward_start")
        assertEquals("b1", FakeTransport.text(start, "binding"))
        assertEquals("127.0.0.1:27311", FakeTransport.text(start, "listen"))
        assertEquals("tcp", FakeTransport.text(start, "protocol"))
        assertEquals(open, start["open"])
    }

    @Test
    fun portZeroTakesTheSystemsPick() {
        fake.answer = { buildJsonObject { put("listen", "127.0.0.1:41022") } }
        assertEquals(ChannelResult.Ok(41022), runBlocking { forwarder.start("b1", 0, "tcp", open) })
    }

    @Test
    fun aNumberThatCannotBeBoundIsPortTaken() {
        fake.answer = {
            buildJsonObject {
                put("code", "port_taken")
                put("params", buildJsonObject { put("port", 27311) })
            }
        }
        assertEquals(
            "port_taken",
            (
                runBlocking {
                    forwarder.start("b1", 27311, "udp", open)
                } as ChannelResult.Refused
                ).code,
        )
    }

    @Test
    fun stopNamesTheListenerAndItsProtocol() {
        fake.answer = { JsonObject(emptyMap()) }
        runBlocking { forwarder.stop(25001, "udp") }
        val stop = fake.nextCommand("forward_stop") ?: error("no forward_stop")
        assertEquals("127.0.0.1:25001", FakeTransport.text(stop, "listen"))
        assertEquals("udp", FakeTransport.text(stop, "protocol"))
    }
}
