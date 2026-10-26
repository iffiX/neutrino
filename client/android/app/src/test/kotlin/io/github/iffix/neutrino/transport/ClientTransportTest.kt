package io.github.iffix.neutrino.transport

import io.github.iffix.neutrino.channel.ChannelResult
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.channels.ReceiveChannel
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ClientTransportTest {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    @After
    fun end() {
        scope.cancel()
    }

    private fun started(fake: FakeTransport): ClientTransport =
        ClientTransport(fake, "/data", { fake }, scope, log = {}).also { it.start() }

    private fun next(events: ReceiveChannel<TransportEvent>): TransportEvent = runBlocking {
        withTimeout(5000) { events.receive() }
    }

    @Test
    fun theLibraryStartsInTheAppsDirectoryWithAFreshSecretAndTheControlConnectionOpensWithIt() {
        val fake = FakeTransport()
        val transport = started(fake)
        val answer = runBlocking { transport.command("round", buildJsonObject { put("binding", "b1") }) }
        assertTrue(answer is ChannelResult.Ok)
        assertTrue(Regex("[0-9a-f]{64}").matches(fake.secret))
        val line = fake.commands.poll(5, TimeUnit.SECONDS)
        assertEquals("round", FakeTransport.text(line, "command"))
        assertEquals("b1", FakeTransport.text(line, "binding"))
    }

    @Test
    fun anAnswerWithACodeIsTheCommandsRefusal() {
        val fake = FakeTransport()
        fake.answer = {
            buildJsonObject {
                put("code", "port_taken")
                put("params", buildJsonObject { put("port", 24001) })
            }
        }
        val transport = started(fake)
        val answer = runBlocking { transport.command("forward_start", JsonObject(emptyMap())) }
        assertEquals("port_taken", (answer as ChannelResult.Refused).code)
        assertEquals("24001", answer.wordParams["port"])
    }

    @Test
    fun eachHubsEventsAndFramesReachItsOwnSubscriptionInOrder() {
        val fake = FakeTransport()
        val transport = started(fake)
        val first = transport.subscribe("b1")
        val second = transport.subscribe("b2")
        runBlocking { transport.command("round", JsonObject(emptyMap())) }
        fake.event("session_open", "b1", "address" to "tcp://192.168.100.1:8443", "path" to "lan", "handshake_ms" to 3)
        fake.event("round_end", "b2", "code" to "hub_unreachable", "next_round_s" to 10)
        fake.frame("b1", buildJsonObject { put("type", "pong") })
        assertEquals(TransportEvent.SessionOpen("tcp://192.168.100.1:8443", "lan", 3), next(first))
        val round = next(second) as TransportEvent.RoundEnd
        assertEquals("hub_unreachable", round.refusal?.code)
        assertEquals(10L, round.nextRoundS)
        assertEquals(JsonPrimitive("pong"), (next(first) as TransportEvent.Frame).frame["type"])
    }

    @Test
    fun aFrameLineNamesTheBindingBesideTheFrame() {
        val fake = FakeTransport()
        val transport = started(fake)
        runBlocking { transport.command("round", JsonObject(emptyMap())) }
        assertTrue(transport.frame("b1", buildJsonObject { put("type", "ping") }))
        val (binding, frame) = fake.nextFrame("ping") ?: error("no frame")
        assertEquals("b1", binding)
        assertEquals(JsonPrimitive("ping"), frame["type"])
    }

    @Test
    fun aControlConnectionThatDropsOpensAgainAndEveryHubIsToldToDialAgain() {
        val fake = FakeTransport()
        val transport = started(fake)
        val events = transport.subscribe("b1")
        runBlocking { transport.command("round", JsonObject(emptyMap())) }
        fake.dropControl()
        assertEquals(TransportEvent.Restarted, next(events))
        assertTrue(runBlocking { transport.command("round", JsonObject(emptyMap())) } is ChannelResult.Ok)
    }

    @Test
    fun noLibraryRefusesEverything() {
        val fake = FakeTransport(isMissing = true)
        val transport = started(fake)
        Thread.sleep(200)
        assertEquals(
            "transport_missing",
            (
                runBlocking {
                    transport.command("dial", JsonObject(emptyMap()))
                } as ChannelResult.Refused
                ).code,
        )
        assertEquals("transport_missing", (transport.open("b1", JsonObject(emptyMap())) as ChannelResult.Refused).code)
    }

    @Test
    fun aForwardEndIsPublishedWithItsProtocolAndCode() {
        val fake = FakeTransport()
        val transport = started(fake)
        val ends = mutableListOf<TransportForwardEnd>()
        val collector = scope.launch { transport.forwardEnds.collect { synchronized(ends) { ends += it } } }
        runBlocking { transport.command("round", JsonObject(emptyMap())) }
        Thread.sleep(100)
        fake.send(
            buildJsonObject {
                put("event", "forward_end")
                put("listen", "127.0.0.1:24100")
                put("protocol", "udp")
                put("code", "agent_offline")
                put("params", buildJsonObject { put("device", "d1") })
            },
        )
        val until = System.currentTimeMillis() + 5000
        while (ends.isEmpty() && System.currentTimeMillis() < until) Thread.sleep(10)
        collector.cancel()
        assertEquals(TransportForwardEnd("127.0.0.1:24100", "udp", ends.single().refusal), ends.single())
        assertEquals("agent_offline", ends.single().refusal?.code)
    }
}
