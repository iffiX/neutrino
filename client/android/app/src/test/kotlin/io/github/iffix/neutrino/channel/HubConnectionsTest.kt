package io.github.iffix.neutrino.channel

import io.github.iffix.neutrino.GoldenSchema
import io.github.iffix.neutrino.binding.BindingStore
import io.github.iffix.neutrino.binding.FakeSecretSealer
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

@OptIn(ExperimentalCoroutinesApi::class)
class HubConnectionsTest {
    @get:Rule
    val folder = TemporaryFolder()

    private val link = (EnrollmentLink.parse(Samples.link(Samples.clientPayload)) as ChannelResult.Ok).value
    private val transport = FakeHubTransport { FakeHubTransport.silent }

    private fun TestScope.connections(): Pair<HubConnections, BindingStore> {
        val store = BindingStore(folder.root.resolve("b.sealed"), FakeSecretSealer())
        return HubConnections(store, transport, Samples.machine, { null }, backgroundScope) to store
    }

    @Test
    fun aJoinKeepsThePendingBindingAtOnceAndAsksTheHubNothing() = runTest {
        val (connections, store) = connections()
        val binding = (connections.join(link) as ChannelResult.Ok).value
        assertEquals(true, binding.isPending)
        assertEquals("ticket-1", binding.ticket)
        assertEquals("", binding.token)
        assertEquals("https://192.168.100.1:8443", binding.gatewayUrl)
        assertEquals(link.urls, binding.gatewayUrls)
        assertEquals(listOf("netbird", "easytier"), binding.overlays.map { it.provider })
        assertEquals(binding, store.get(binding.id))
        assertEquals(emptyList<Any>(), transport.posts)
    }

    @Test
    fun aSecondJoinWithTheSameTicketIsTheSameBinding() = runTest {
        val (connections, store) = connections()
        val first = (connections.join(link) as ChannelResult.Ok).value
        assertEquals(first, (connections.join(link) as ChannelResult.Ok).value)
        assertEquals(1, store.bindings.value.size)
    }

    @Test
    fun theJoinedHubsRowIsPendingWithTheLinksFirstAddressAndItsNetworks() = runTest {
        val (connections, _) = connections()
        connections.start()
        connections.startJoin(Samples.link(Samples.clientPayload))
        runCurrent()
        val row = connections.views.first().single()
        assertEquals(HubConnection.PENDING, row.connection)
        assertEquals("ui.state.pending", "ui.state.${row.connection.wireName}")
        assertEquals("https://192.168.100.1:8443", row.binding.gatewayUrl)
        assertEquals(listOf("netbird", "easytier"), row.binding.overlays.map { it.provider })
    }

    @Test
    fun leavingAPendingBindingForgetsItWithoutAskingTheHub() = runTest {
        val (connections, store) = connections()
        val binding = (connections.join(link) as ChannelResult.Ok).value
        assertEquals(ChannelResult.Ok(Unit), connections.leave(binding.id))
        assertNull(store.get(binding.id))
        assertEquals(emptyList<Any>(), transport.posts)
    }

    @Test
    fun joiningAgainDropsTheOldBinding() = runTest {
        val welcoming = FakeHubTransport { FakeHubTransport.welcoming }
        welcoming.answers["https://192.168.100.1:8443" to "/api/channel/join"] =
            ChannelResult.Ok(JsonObject(mapOf("id" to JsonPrimitive("b1"), "token" to JsonPrimitive("t9"))))
        val store = BindingStore(folder.root.resolve("b.sealed"), FakeSecretSealer())
        val left = mutableListOf<String>()
        val connections = HubConnections(store, welcoming, Samples.machine, { null }, backgroundScope) { left += it }
        store.put(Samples.binding)
        val pending = (connections.join(link) as ChannelResult.Ok).value
        connections.start()
        runCurrent()
        assertEquals(listOf(pending.id), store.bindings.value.map { it.id })
        assertEquals("b1", store.get(pending.id)?.boundId)
        assertEquals(listOf("b1"), left)
    }

    @Test
    fun leavingForgetsTheBindingOnceTheHubAgreesOrNoLongerKnowsIt() = runTest {
        val (connections, store) = connections()
        store.put(Samples.binding)
        transport.answers["https://192.168.100.1:8443" to "/api/channel/leave"] =
            ChannelResult.refused("binding_unknown")
        assertEquals(ChannelResult.Ok(Unit), connections.leave("b1"))
        assertNull(store.get("b1"))
        assertEquals(emptyList<String>(), GoldenSchema.problems(transport.posts.single().third, "ChannelLeaveRequest"))
    }

    @Test
    fun anUnreachableHubKeepsTheBinding() = runTest {
        val (connections, store) = connections()
        store.put(Samples.binding)
        assertEquals("hub_unreachable", (connections.leave("b1") as ChannelResult.Refused).code)
        assertEquals(Samples.binding, store.get("b1"))
    }

    @Test
    fun aLeaveIsAJobOnTheRowAndAFailureIsItsErrorLine() = runTest {
        val gate = CompletableDeferred<Unit>()
        val gated = object : HubTransport by transport {
            override suspend fun post(
                baseUrl: String,
                path: String,
                fingerprint: String,
                body: JsonObject,
            ): ChannelResult<JsonObject> {
                gate.await()
                return transport.post(baseUrl, path, fingerprint, body)
            }
        }
        val store = BindingStore(folder.root.resolve("b.sealed"), FakeSecretSealer())
        val connections = HubConnections(store, gated, Samples.machine, { null }, backgroundScope)
        store.put(Samples.binding)
        connections.start()
        runCurrent()
        connections.startLeave("b1")
        runCurrent()
        assertEquals(true, connections.views.first().single().jobs.isLeaving)
        connections.startLeave("b1")
        gate.complete(Unit)
        runCurrent()
        val row = connections.views.first().single()
        assertEquals(false, row.jobs.isLeaving)
        assertEquals("hub_unreachable", row.jobError?.code)
        assertEquals(Samples.binding.storedUrls.size, transport.posts.count { it.second == "/api/channel/leave" })
        connections.refresh()
        assertNull(connections.views.first().single().jobError)
    }

    @Test
    fun aJoinIsAJobThatEndsInTheBindingOrTheCode() = runTest {
        val (connections, store) = connections()
        connections.startJoin("not a link")
        runCurrent()
        assertEquals("link_unreadable", connections.join.value.refusal?.code)
        connections.startJoin(Samples.link(Samples.clientPayload))
        assertEquals(true, connections.join.value.isJoining)
        runCurrent()
        assertEquals(store.bindings.value.single().id, connections.join.value.joinedId)
        connections.clearJoin()
        assertEquals(HubJoin(), connections.join.value)
    }

    private val shortLink = "neutrino://enroll/ticket-1@192.168.100.1:8443/${Samples.FINGERPRINT}"
    private val enrollAt = "https://192.168.100.1:8443" to "/api/channel/enroll?ticket=ticket-1"

    @Test
    fun aScannedShortLinkFetchesTheLongLinksObjectOnThePinThenJoins() = runTest {
        val (connections, store) = connections()
        assertEquals(emptyList<String>(), GoldenSchema.problems(Samples.clientPayload, "ChannelEnrollView"))
        transport.readings[enrollAt] = ChannelResult.Ok(Samples.clientPayload)
        connections.startJoin(shortLink)
        runCurrent()
        val binding = store.bindings.value.single()
        assertEquals(binding.id, connections.join.value.joinedId)
        assertEquals(Triple(enrollAt.first, enrollAt.second, Samples.FINGERPRINT), transport.gets.single())
        assertEquals(link.urls, binding.gatewayUrls)
        assertEquals("ticket-1", binding.ticket)
        assertEquals(listOf("netbird", "easytier"), binding.overlays.map { it.provider })
    }

    @Test
    fun aShortLinkWhoseAddressDoesNotAnswerIsLinkUnreachable() = runTest {
        val (connections, store) = connections()
        connections.startJoin(shortLink)
        runCurrent()
        assertEquals("link_unreachable", connections.join.value.refusal?.code)
        assertEquals(emptyList<Any>(), store.bindings.value)
    }

    @Test
    fun aShortLinkOnAnotherCertificateOrASpentTicketKeepsTheHubsCode() = runTest {
        val (connections, store) = connections()
        for (code in listOf("hub_untrusted", "ticket_spent")) {
            transport.readings[enrollAt] = ChannelResult.refused(code)
            connections.startJoin(shortLink)
            runCurrent()
            assertEquals(code, connections.join.value.refusal?.code)
        }
        assertEquals(emptyList<Any>(), store.bindings.value)
    }
}
