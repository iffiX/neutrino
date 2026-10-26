package io.github.iffix.neutrino.channel

import io.github.iffix.neutrino.binding.BindingStore
import io.github.iffix.neutrino.binding.FakeSecretSealer
import io.github.iffix.neutrino.transport.ClientTransport
import io.github.iffix.neutrino.transport.FakeTransport
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class HubConnectionsTest {
    @get:Rule
    val folder = TemporaryFolder()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val fake = FakeTransport()
    private val transport = ClientTransport(fake, "/data", { fake }, scope, log = {}).also { it.start() }
    private val link = (EnrollmentLink.parse(Samples.link(Samples.clientPayload)) as ChannelResult.Ok).value
    private val left = mutableListOf<String>()
    private val store by lazy { BindingStore(folder.root.resolve("b.sealed"), FakeSecretSealer()) }
    private val connections by lazy {
        HubConnections(store, transport, Samples.machine, { null }, scope) { left += it }
    }

    @After
    fun end() {
        scope.cancel()
    }

    private fun eventually(what: String, check: () -> Boolean) {
        val until = System.currentTimeMillis() + 5000
        while (System.currentTimeMillis() < until) {
            if (check()) return
            Thread.sleep(10)
        }
        throw AssertionError("never: $what")
    }

    @Test
    fun aJoinKeepsTheBindingWithBothKeys() {
        val binding = (connections.join(link) as ChannelResult.Ok).value
        assertTrue(binding.isPending)
        assertEquals("ticket-1", binding.ticket)
        assertEquals("", binding.token)
        assertEquals(Samples.HUB_KEY, binding.hubKey)
        assertTrue(Regex("[0-9a-f]{64}").matches(binding.privateKey))
        assertEquals("tcp://192.168.100.1:8443", binding.gatewayUrl)
        assertEquals(listOf("netbird", "easytier"), binding.overlays.map { it.provider })
        assertEquals(binding, store.get(binding.id))
        assertTrue(fake.commands.isEmpty())
    }

    @Test
    fun aSecondJoinWithTheSameTicketIsTheSameBinding() {
        val first = (connections.join(link) as ChannelResult.Ok).value
        assertEquals(first, (connections.join(link) as ChannelResult.Ok).value)
        assertEquals(1, store.bindings.value.size)
        val other = (connections.join(link.copy(ticket = "ticket-2")) as ChannelResult.Ok).value
        assertTrue(other.privateKey != first.privateKey)
    }

    @Test
    fun theJoinedHubsRowReadsConnectingAndItsTicketGoesToTheTransportsJoin() {
        fake.answer = {
            Thread.sleep(1000)
            JsonObject(emptyMap())
        }
        connections.start()
        connections.startJoin(Samples.link(Samples.clientPayload))
        val join = fake.nextCommand("join") ?: error("no join")
        assertEquals("ticket-1", FakeTransport.text(join, "ticket"))
        val row = runBlocking { connections.views.first { it.isNotEmpty() } }.single()
        assertEquals(HubConnection.CONNECTING, row.connection)
        assertEquals("tcp://192.168.100.1:8443", row.binding.gatewayUrl)
    }

    @Test
    fun leavingAPendingBindingForgetsItWithoutTellingTheHub() {
        val binding = (connections.join(link) as ChannelResult.Ok).value
        assertEquals(ChannelResult.Ok(Unit), connections.leave(binding.id))
        assertNull(store.get(binding.id))
        assertNull(fake.nextCommand("leave", seconds = 1))
    }

    @Test
    fun aLeaveForgetsTheBindingAtOnceAndTellsTheHubThroughTheTransport() {
        store.put(Samples.binding)
        assertEquals(ChannelResult.Ok(Unit), connections.leave("b1"))
        assertNull(store.get("b1"))
        val leave = fake.nextCommand("leave") ?: error("no leave")
        assertEquals("b1", FakeTransport.text(leave, "binding"))
        assertEquals(Samples.HUB_KEY, FakeTransport.text(leave, "hub_key"))
        assertEquals(Samples.binding.psk, FakeTransport.text(leave, "psk"))
        assertEquals("client", FakeTransport.text(leave, "role"))
    }

    @Test
    fun aBindingOf05sShapeIsForgottenWithNothingTold() {
        store.put(Samples.binding.copy(hubKey = "", privateKey = ""))
        assertEquals(ChannelResult.Ok(Unit), connections.leave("b1"))
        assertNull(fake.nextCommand("leave", seconds = 1))
    }

    @Test
    fun aStartKeepsOneBindingPerHubAndTellsTheHubForEachOneEnded() {
        store.put(Samples.binding.copy(id = "old", hubId = "hub-1"))
        store.put(Samples.binding.copy(id = "new", hubId = "hub-1"))
        connections.start()
        assertEquals(listOf("new"), store.bindings.value.map { it.id })
        assertEquals(listOf("old"), left)
        assertEquals("old", FakeTransport.text(fake.nextCommand("leave") ?: error("no leave"), "binding"))
    }

    @Test
    fun aWelcomeNamingAHubAnotherBindingHoldsEndsThatBindingAndTellsTheHub() {
        store.put(Samples.binding.copy(id = "old", hubId = "hub-1"))
        store.put(Samples.binding.copy(id = "fresh"))
        connections.start()
        eventually("dialled") { fake.commands.count { FakeTransport.text(it, "command") == "dial" } >= 2 }
        fake.event(
            "session_open",
            "fresh",
            "address" to "tcp://192.168.100.1:8443",
            "path" to "lan",
            "handshake_ms" to 1,
        )
        eventually("hello") { fake.frames.any { it.first == "fresh" } }
        fake.frame(
            "fresh",
            buildJsonObject {
                put("type", "welcome")
                put("protocol", 4)
                put("role", "hub")
                put("id", "hub-1")
                put("name", "Neutrino")
                put("software", "neutrino_hub/0.6.0")
            },
        )
        eventually("one binding") { store.bindings.value.map { it.id } == listOf("fresh") }
        assertEquals(listOf("old"), left)
        assertTrue(fake.nextCommand("leave") != null)
    }

    @Test
    fun aJoinThatLandsOnAnotherBindingsIdEndsItWithNothingTold() {
        store.put(Samples.binding.copy(id = "c9", hubId = "hub-1"))
        fake.answer = { line ->
            if (FakeTransport.text(line, "command") == "join") {
                buildJsonObject {
                    put("binding_id", "c9")
                    put("token", "t9")
                }
            } else {
                JsonObject(emptyMap())
            }
        }
        val pending = (connections.join(link) as ChannelResult.Ok).value
        connections.start()
        eventually("one binding") { store.bindings.value.map { it.id } == listOf(pending.id) }
        assertEquals("c9", store.get(pending.id)?.boundId)
        assertEquals(listOf("c9"), left)
        assertNull(fake.nextCommand("leave", seconds = 1))
    }
}
