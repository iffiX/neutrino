package io.github.iffix.neutrino.channel

import io.github.iffix.neutrino.CLIENT_LEAVE_TELL_TIMEOUT_S
import io.github.iffix.neutrino.GoldenSchema
import io.github.iffix.neutrino.binding.BindingStore
import io.github.iffix.neutrino.binding.FakeSecretSealer
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
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
    private val sealer = FakeSecretSealer()

    private fun TestScope.connections(): Pair<HubConnections, BindingStore> {
        val store = BindingStore(folder.root.resolve("b.sealed"), sealer)
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
        assertEquals(Samples.clientProviders, binding.overlays.map { it.provider })
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
        assertEquals(Samples.clientProviders, row.binding.overlays.map { it.provider })
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

    private val leaveAt = "https://192.168.100.1:8443" to "/api/channel/leave"

    private fun gated(gate: CompletableDeferred<Unit>): HubTransport = object : HubTransport by transport {
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

    @Test
    fun aLeaveForgetsTheBindingBeforeTheHubAnswersAndTellsItOnce() = runTest {
        for (answer in listOf(ChannelResult.refused("token_rejected"), ChannelResult.refused("hub_untrusted"))) {
            transport.posts.clear()
            transport.answers[leaveAt] = answer
            val gate = CompletableDeferred<Unit>()
            val store = BindingStore(folder.root.resolve("b.sealed"), sealer)
            val connections = HubConnections(store, gated(gate), Samples.machine, { null }, backgroundScope)
            store.put(Samples.binding)
            assertEquals(ChannelResult.Ok(Unit), connections.leave("b1"))
            assertNull(store.get("b1"))
            runCurrent()
            assertEquals(emptyList<Any>(), transport.posts)
            gate.complete(Unit)
            runCurrent()
            assertNull(store.get("b1"))
            val told = transport.posts.single()
            assertEquals(leaveAt, told.first to told.second)
            assertEquals(emptyList<String>(), GoldenSchema.problems(told.third, "ChannelLeaveRequest"))
        }
    }

    @Test
    fun anUnreachableHubIsToldAtEachAddressAndTheBindingIsGoneAlready() = runTest {
        val (connections, store) = connections()
        store.put(Samples.binding)
        assertEquals(ChannelResult.Ok(Unit), connections.leave("b1"))
        assertNull(store.get("b1"))
        runCurrent()
        assertEquals(Samples.binding.storedUrls.size, transport.posts.count { it.second == "/api/channel/leave" })
    }

    @Test
    fun aHubThatNeverAnswersTheLeaveIsLetGoAfterTheShortTimeout() = runTest {
        val gate = CompletableDeferred<Unit>()
        val store = BindingStore(folder.root.resolve("b.sealed"), sealer)
        val connections = HubConnections(store, gated(gate), Samples.machine, { null }, backgroundScope)
        store.put(Samples.binding)
        connections.leave("b1")
        advanceTimeBy(CLIENT_LEAVE_TELL_TIMEOUT_S * 1000 + 1)
        gate.complete(Unit)
        runCurrent()
        assertEquals(emptyList<Any>(), transport.posts)
        assertNull(store.get("b1"))
    }

    @Test
    fun aHubWhoseIdentityChangedIsLeftWithOnePress() = runTest {
        val untrusted = FakeHubTransport { FakeHubTransport.impostor }
        untrusted.answers[leaveAt] = ChannelResult.refused("hub_untrusted", "url" to "x")
        val store = BindingStore(folder.root.resolve("b.sealed"), FakeSecretSealer())
        val connections = HubConnections(store, untrusted, Samples.machine, { null }, backgroundScope)
        store.put(Samples.binding)
        connections.start()
        advanceTimeBy(1000)
        assertEquals("hub_untrusted", connections.views.first().single().lastError?.code)
        connections.startLeave("b1")
        runCurrent()
        assertEquals(emptyList<HubView>(), connections.views.first())
        advanceTimeBy(120_000)
        assertEquals(emptyList<HubView>(), connections.views.first())
        assertNull(store.get("b1"))
    }

    @Test
    fun aLeaveIsAJobOnTheRowThatEndsWithTheRowAndNoErrorLine() = runTest {
        transport.answers[leaveAt] = ChannelResult.refused("token_rejected")
        val gate = CompletableDeferred<Unit>()
        val store = BindingStore(folder.root.resolve("b.sealed"), FakeSecretSealer())
        val left = mutableListOf<String>()
        val connections = HubConnections(store, gated(gate), Samples.machine, { null }, backgroundScope) {
            left += it
        }
        store.put(Samples.binding)
        connections.start()
        runCurrent()
        connections.startLeave("b1")
        connections.startLeave("b1")
        assertEquals(listOf("b1"), left)
        runCurrent()
        assertEquals(emptyList<HubView>(), connections.views.first())
        gate.complete(Unit)
        runCurrent()
        assertEquals(1, transport.posts.count { it.second == "/api/channel/leave" })
        store.put(Samples.binding)
        runCurrent()
        val row = connections.views.first().single()
        assertEquals(false, row.jobs.isLeaving)
        assertNull(row.jobError)
    }

    @Test
    fun aClosedNoticeIsGoneAndARefreshDropsEveryNotice() = runTest {
        val refusing = FakeHubTransport { FakeHubTransport.refusing("binding_unknown") }
        val store = BindingStore(folder.root.resolve("b.sealed"), sealer)
        val connections = HubConnections(store, refusing, Samples.machine, { null }, backgroundScope)
        store.put(Samples.binding)
        store.put(Samples.binding.copy(id = "b2"))
        connections.start()
        runCurrent()
        val (first, second) = connections.notices.value
        assertEquals("binding_unknown", first.refusal.code)
        connections.closeNotice(first)
        assertEquals(listOf(second), connections.notices.value)
        connections.refresh()
        assertEquals(emptyList<HubNotice>(), connections.notices.value)
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

    private val scannedLink = Samples.link(Samples.clientPayload)

    private val joinAt = "https://192.168.100.1:8443" to "/api/channel/join"

    private fun TestScope.reachable(): Triple<HubConnections, BindingStore, FakeHubTransport> {
        val hub = FakeHubTransport { FakeHubTransport.welcoming }
        hub.answers[joinAt] =
            ChannelResult.Ok(JsonObject(mapOf("id" to JsonPrimitive("c9"), "token" to JsonPrimitive("t9"))))
        val store = BindingStore(folder.root.resolve("b.sealed"), sealer)
        return Triple(HubConnections(store, hub, Samples.machine, { null }, backgroundScope), store, hub)
    }

    @Test
    fun aScannedLinkIsKeptPendingAtOnceWithEveryAddressAndOverlay() = runTest {
        val (connections, store) = connections()
        connections.startJoin(scannedLink)
        runCurrent()
        val binding = store.bindings.value.single()
        assertEquals(binding.id, connections.join.value.joinedId)
        assertEquals(true, binding.isPending)
        assertEquals("ticket-1", binding.ticket)
        assertEquals(Samples.FINGERPRINT, binding.fingerprint)
        assertEquals(link.urls, binding.gatewayUrls)
        assertEquals(Samples.clientProviders, binding.overlays.map { it.provider })
        assertEquals(emptyList<Any>(), transport.posts)
    }

    @Test
    fun aSilentHubKeepsTheScannedRowPending() = runTest {
        val (connections, store) = connections()
        connections.start()
        connections.startJoin(scannedLink)
        runCurrent()
        val row = connections.views.first().single()
        assertEquals(HubConnection.PENDING, row.connection)
        assertEquals("https://192.168.100.1:8443", row.binding.gatewayUrl)
        assertEquals(Samples.clientProviders, row.binding.overlays.map { it.provider })
        assertEquals("ticket-1", store.bindings.value.single().ticket)
    }

    @Test
    fun aRoundThatReachesTheHubJoinsWithNothingFetchedFirst() = runTest {
        val (connections, store, hub) = reachable()
        connections.start()
        connections.startJoin(scannedLink)
        runCurrent()
        assertEquals(joinAt, hub.posts.single().let { it.first to it.second })
        val binding = store.bindings.value.single()
        assertEquals("c9" to "t9", binding.boundId to binding.token)
        assertEquals(HubConnection.CONNECTED, connections.views.first().single().connection)
    }

    @Test
    fun aKeptScannedLinkIsJoinedByARoundAfterARestart() = runTest {
        val (scanned, _) = connections()
        scanned.startJoin(scannedLink)
        runCurrent()
        val (connections, store, hub) = reachable()
        val kept = store.bindings.value.single()
        assertEquals("ticket-1", kept.ticket)
        connections.start()
        runCurrent()
        assertEquals(joinAt, hub.posts.single().let { it.first to it.second })
        assertEquals("c9", store.get(kept.id)?.boundId)
    }
}
