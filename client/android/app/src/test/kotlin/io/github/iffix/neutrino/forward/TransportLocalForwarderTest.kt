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
        assertEquals(ChannelResult.Ok(27311), runBlocking { forwarder.start("b1", 27311, "tcp", open, false) })
        val start = fake.nextCommand("forward_start") ?: error("no forward_start")
        assertEquals("b1", FakeTransport.text(start, "binding"))
        assertEquals("127.0.0.1:27311", FakeTransport.text(start, "listen"))
        assertEquals("tcp", FakeTransport.text(start, "protocol"))
        assertEquals(open, start["open"])
    }

    @Test
    fun portZeroTakesTheSystemsPick() {
        fake.answer = { buildJsonObject { put("listen", "127.0.0.1:41022") } }
        assertEquals(ChannelResult.Ok(41022), runBlocking { forwarder.start("b1", 0, "tcp", open, false) })
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
                    forwarder.start("b1", 27311, "udp", open, false)
                } as ChannelResult.Refused
                ).code,
        )
    }

    @Test
    fun stopNamesTheListenerAndItsProtocol() {
        fake.answer = { JsonObject(emptyMap()) }
        runBlocking { forwarder.stop(25001, "udp", false) }
        val stop = fake.nextCommand("forward_stop") ?: error("no forward_stop")
        assertEquals("127.0.0.1:25001", FakeTransport.text(stop, "listen"))
        assertEquals("udp", FakeTransport.text(stop, "protocol"))
    }

    @Test
    fun aBrowserForwardListensOnBothLoopbacksAtOneNumber() {
        fake.answer = { command ->
            buildJsonObject { put("listen", FakeTransport.text(command, "listen")) }
        }
        assertEquals(ChannelResult.Ok(27311), runBlocking { forwarder.start("b1", 27311, "tcp", open, true) })
        val first = fake.nextCommand("forward_start") ?: error("no forward_start")
        val second = fake.nextCommand("forward_start") ?: error("no second forward_start")
        assertEquals("127.0.0.1:27311", FakeTransport.text(first, "listen"))
        assertEquals("[::1]:27311", FakeTransport.text(second, "listen"))
        runBlocking { forwarder.stop(27311, "tcp", true) }
        val stops = List(2) { fake.nextCommand("forward_stop") ?: error("no forward_stop") }
        assertEquals(listOf("127.0.0.1:27311", "[::1]:27311"), stops.map { FakeTransport.text(it, "listen") })
    }

    @Test
    fun aHeldSecondLoopbackIsPortTakenAndClosesTheFirst() {
        fake.answer = { command ->
            val listen = FakeTransport.text(command, "listen")
            if (FakeTransport.text(command, "command") == "forward_start" && listen.startsWith("[::1]")) {
                buildJsonObject {
                    put("code", "port_taken")
                    put("params", buildJsonObject { put("port", 27311) })
                }
            } else {
                buildJsonObject { put("listen", listen) }
            }
        }
        val started = runBlocking { forwarder.start("b1", 27311, "tcp", open, true) }
        assertEquals("port_taken", (started as ChannelResult.Refused).code)
        val stop = fake.nextCommand("forward_stop") ?: error("no forward_stop")
        assertEquals("127.0.0.1:27311", FakeTransport.text(stop, "listen"))
    }
}
