package io.github.iffix.neutrino.channel

import io.github.iffix.neutrino.GoldenSchema
import io.github.iffix.neutrino.binding.BindingStore
import io.github.iffix.neutrino.binding.FakeSecretSealer
import io.github.iffix.neutrino.binding.HubBinding
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.async
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

@OptIn(ExperimentalCoroutinesApi::class)
class HubSessionTest {
    @get:Rule
    val folder = TemporaryFolder()

    private val unbound = mutableListOf<String>()

    private val joined = mutableListOf<Pair<String, String>>()

    private val pending = Samples.binding.copy(token = "", ticket = "ticket-1")

    private fun session(
        transport: FakeHubTransport,
        nameAddress: String? = null,
        binding: HubBinding = Samples.binding,
    ): Pair<HubSession, BindingStore> {
        val store = BindingStore(folder.root.resolve("b.sealed"), FakeSecretSealer())
        store.put(binding)
        val session = HubSession(
            "b1",
            store,
            transport,
            Samples.machine,
            { nameAddress },
            { id, _ -> unbound += id },
            { id, hubId -> joined += id to hubId },
        )
        return session to store
    }

    private fun spent(id: String = "c9", token: String = "t9") =
        ChannelResult.Ok(JsonObject(mapOf("id" to JsonPrimitive(id), "token" to JsonPrimitive(token))))

    private fun TestScope.served(session: HubSession) = backgroundScope.async {
        session.runOnce()
    }.also { runCurrent() }

    @Test
    fun theHandshakeSaysHelloTakesTheWelcomeAndReports() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.welcoming }
        val (session, store) = session(transport)
        served(session)
        val socket = transport.dialled.single().second
        assertEquals(listOf("hello", "report"), socket.texts.map { it["type"]!!.jsonPrimitive.content })
        assertEquals("secret-token", socket.texts[0]["token"]!!.jsonPrimitive.content)
        assertEquals(HubConnection.CONNECTED, session.view.value.connection)
        assertEquals("Neutrino", store.get("b1")?.hubName)
        assertEquals("neutrino_hub/0.5.0", session.view.value.software)
    }

    @Test
    fun aStateIsTakenNotedAndAnswered() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.welcoming }
        val (session, store) = session(transport)
        served(session)
        val (_, socket, events) = transport.dialled.single()
        events.trySend(
            ChannelSocketEvent.Text(
                """{"type":"state","hash":"h9","urls":["https://10.0.0.1:8443"],
                   "overlays":[{"provider":"netbird","setup_key":"K"}],
                   "services":[{"id":"s","type":"port","title":"SSH","payload":{"host":"h","port":22},"source":"declared"}]}""",
            ),
        )
        runCurrent()
        assertEquals(listOf("https://10.0.0.1:8443"), store.get("b1")?.gatewayUrls)
        assertEquals("netbird", store.get("b1")?.overlays?.single()?.provider)
        assertEquals("SSH", session.view.value.services.single().title)
        assertEquals("h9", socket.sent("report").last()["state_hash"]!!.jsonPrimitive.content)
    }

    @Test
    fun aReportGoesUpEveryThirtySeconds() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.welcoming }
        val (session, _) = session(transport)
        served(session)
        val socket = transport.dialled.single().second
        advanceTimeBy(30_001)
        assertEquals(2, socket.sent("report").size)
    }

    @Test
    fun aBrokenWireBacksOffFromFiveToSixty() = runTest {
        val (session, _) = session(FakeHubTransport { FakeHubTransport.silent })
        val waits = List(6) { session.runOnce() }
        assertEquals(listOf(5L, 10L, 20L, 40L, 60L, 60L), waits)
        assertEquals("hub_unreachable", session.view.value.lastError?.code)
    }

    @Test
    fun aRoundTriesEveryAddressInOrder() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.silent }
        val (session, _) = session(transport, nameAddress = "10.9.9.9")
        session.runOnce()
        assertEquals(
            listOf("https://10.9.9.9:8443", "https://192.168.100.1:8443", "https://100.72.4.1:8443"),
            transport.dialled.map { it.first },
        )
    }

    @Test
    fun anotherHubAnsweringTheNameIsSkipped() = runTest {
        val transport =
            FakeHubTransport { url ->
                if (url.contains("10.9.9.9")) FakeHubTransport.impostor else FakeHubTransport.welcoming
            }
        val (session, _) = session(transport, nameAddress = "10.9.9.9")
        served(session)
        advanceTimeBy(1_500)
        assertEquals(HubConnection.CONNECTED, session.view.value.connection)
    }

    @Test
    fun aStoredAddressWithAnotherCertificateIsRecordedAndWaitsTheMinute() = runTest {
        val (session, _) = session(FakeHubTransport { FakeHubTransport.impostor })
        assertEquals(60L, session.runOnce())
        assertEquals("hub_untrusted", session.view.value.lastError?.code)
    }

    @Test
    fun aProtocolRefusalKeepsTheBindingAndAsksAgainInAMinute() = runTest {
        val (session, store) = session(FakeHubTransport { FakeHubTransport.refusing("protocol_too_old") })
        assertEquals(60L, session.runOnce())
        assertEquals("protocol_too_old", session.view.value.lastError?.code)
        assertTrue(store.get("b1") != null)
        assertTrue(unbound.isEmpty())
    }

    @Test
    fun bindingUnknownUnbinds() = runTest {
        val (session, _) = session(FakeHubTransport { FakeHubTransport.refusing("binding_unknown") })
        session.runOnce()
        assertEquals(listOf("b1"), unbound)
        assertEquals(HubConnection.DOWN, session.view.value.connection)
        assertEquals("binding_unknown", session.view.value.lastError?.code)
        assertEquals(2L, session.runOnce())
    }

    @Test
    fun aSocketAnotherReplacedWaitsForAPerson() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.welcoming }
        val (session, _) = session(transport)
        val round = served(session)
        transport.dialled.single().third.trySend(ChannelSocketEvent.Closed(4010, "replaced"))
        assertEquals(2L, round.await())
        assertEquals(HubConnection.REPLACED, session.view.value.connection)
        assertEquals(2L, session.runOnce())
        assertEquals(1, transport.dialled.size)
        session.reconnect()
        served(session)
        assertEquals(2, transport.dialled.size)
    }

    @Test
    fun aRefusedFrameOnAnOpenSocketIsARefusal() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.welcoming }
        val (session, _) = session(transport)
        val round = served(session)
        transport.dialled.single().third.trySend(
            ChannelSocketEvent.Text("""{"type":"refused","code":"role_mismatch"}"""),
        )
        assertEquals(60L, round.await())
        assertEquals("role_mismatch", session.view.value.lastError?.code)
    }

    @Test
    fun aDisabledClientShowsNoServiceAndSaysSo() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.welcoming }
        val (session, _) = session(transport)
        served(session)
        transport.dialled.single().third.trySend(
            ChannelSocketEvent.Text(
                """{"type":"state","hash":"h","is_disabled":true,"services":[{"id":"s","type":"web","title":"t","payload":{},"source":"module"}]}""",
            ),
        )
        runCurrent()
        assertEquals(emptyList<ChannelServiceEntry>(), session.view.value.servicesOf("web"))
        assertEquals(HubConnection.DISABLED, session.view.value.connection)
        transport.dialled.single().third.trySend(
            ChannelSocketEvent.Text("""{"type":"state","hash":"h2","is_disabled":false}"""),
        )
        runCurrent()
        assertEquals(HubConnection.CONNECTED, session.view.value.connection)
    }

    @Test
    fun aServiceStreamIsOpenedOnTheSocketAndItsCloseIsTheMaterial() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.welcoming }
        val (session, _) = session(transport)
        served(session)
        val (_, socket, events) = transport.dialled.single()
        val material = backgroundScope.async { session.openService("ai-1") }
        runCurrent()
        val open = socket.sent("open").single()
        assertEquals("service", open["kind"]!!.jsonPrimitive.content)
        assertEquals("ai-1", open["id"]!!.jsonPrimitive.content)
        events.trySend(ChannelSocketEvent.Text("""{"type":"close","stream":1,"code":"","params":{"api_key":"k"}}"""))
        assertEquals("k", ((material.await() as ChannelResult.Ok).value["api_key"])!!.jsonPrimitive.content)
    }

    @Test
    fun aRoundStartsConnectingAndARoundWithNoAnswerIsDownWithItsCode() = runTest {
        val (session, _) = session(FakeHubTransport { FakeHubTransport.silent })
        assertEquals(HubConnection.CONNECTING, session.view.value.connection)
        session.runOnce()
        assertEquals(HubConnection.DOWN, session.view.value.connection)
        assertEquals("hub_unreachable", session.view.value.lastError?.code)
        assertEquals(false, session.view.value.hasConnected)
    }

    @Test
    fun aSocketThatClosesIsConnectingWithNoErrorLine() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.welcoming }
        val (session, _) = session(transport)
        val round = served(session)
        assertEquals(true, session.view.value.hasConnected)
        transport.dialled.single().third.trySend(ChannelSocketEvent.Closed(1006, ""))
        assertEquals(5L, round.await())
        assertEquals(HubConnection.CONNECTING, session.view.value.connection)
        assertEquals(null, session.view.value.lastError)
    }

    @Test
    fun aRefreshOnAConnectedHubSendsAReportWithIsRefreshAndEndsOnTheStateFrame() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.welcoming }
        val (session, _) = session(transport)
        session.start(backgroundScope)
        runCurrent()
        val (_, socket, events) = transport.dialled.single()
        assertEquals(true, session.refresh())
        assertEquals(true, session.view.value.jobs.isRefreshing)
        assertEquals(true, socket.sent("report").last()["is_refresh"]!!.jsonPrimitive.boolean)
        events.trySend(ChannelSocketEvent.Text("""{"type":"state","hash":"h3"}"""))
        runCurrent()
        assertEquals(false, session.view.value.jobs.isRefreshing)
        assertEquals(false, socket.sent("report").last()["is_refresh"]!!.jsonPrimitive.boolean)
    }

    @Test
    fun aRefreshEndsAfterTenSecondsWithNoAnswer() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.welcoming }
        val (session, _) = session(transport)
        session.start(backgroundScope)
        runCurrent()
        session.refresh()
        advanceTimeBy(9_999)
        assertEquals(true, session.view.value.jobs.isRefreshing)
        advanceTimeBy(2)
        assertEquals(false, session.view.value.jobs.isRefreshing)
    }

    @Test
    fun aRefreshOnADownHubDropsItsErrorAndRunsARoundNow() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.silent }
        val (session, _) = session(transport)
        session.start(backgroundScope)
        advanceTimeBy(5_500 + 10_500 + 20_500)
        assertEquals(HubConnection.DOWN, session.view.value.connection)
        val before = transport.dialled.size
        session.refresh()
        assertEquals(null, session.view.value.lastError)
        runCurrent()
        assertTrue(transport.dialled.size > before)
        assertEquals(true, session.view.value.jobs.isRefreshing)
        advanceTimeBy(1_100)
        assertEquals(false, session.view.value.jobs.isRefreshing)
        assertEquals("hub_unreachable", session.view.value.lastError?.code)
        val after = transport.dialled.size
        advanceTimeBy(5_500)
        assertTrue(transport.dialled.size > after)
    }

    @Test
    fun aReplacedOrDisabledHubTakesNoRefresh() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.welcoming }
        val (session, _) = session(transport)
        val round = served(session)
        transport.dialled.single().third.trySend(
            ChannelSocketEvent.Text("""{"type":"state","hash":"h","is_disabled":true}"""),
        )
        runCurrent()
        assertEquals(false, session.refresh())
        transport.dialled.single().third.trySend(ChannelSocketEvent.Closed(4010, "replaced"))
        round.await()
        assertEquals(HubConnection.REPLACED, session.view.value.connection)
        assertEquals(false, session.refresh())
        assertEquals(false, session.view.value.jobs.isRefreshing)
    }

    @Test
    fun returningToTheForegroundRunsARoundNowWithTheBackoffAtItsFloor() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.silent }
        val (session, _) = session(transport)
        session.start(backgroundScope)
        advanceTimeBy(20_000)
        val before = transport.dialled.size
        session.resume()
        runCurrent()
        assertEquals(before + 1, transport.dialled.size)
        advanceTimeBy(1_100)
        val afterRound = transport.dialled.size
        advanceTimeBy(5_000)
        assertTrue(transport.dialled.size > afterRound)
    }

    @Test
    fun returningToTheForegroundLeavesAnOpenSocketAlone() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.welcoming }
        val (session, _) = session(transport)
        session.start(backgroundScope)
        runCurrent()
        session.resume()
        runCurrent()
        assertEquals(1, transport.dialled.size)
        assertEquals(HubConnection.CONNECTED, session.view.value.connection)
    }

    @Test
    fun aSocketThatClosesStampsWhenItDropped() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.welcoming }
        val store = BindingStore(folder.root.resolve("b.sealed"), FakeSecretSealer())
        store.put(Samples.binding)
        val session = HubSession("b1", store, transport, Samples.machine, { null }, { _, _ -> }, clock = { 42_000L })
        val round = served(session)
        assertEquals(0L, session.view.value.droppedAtMillis)
        transport.dialled.single().third.trySend(ChannelSocketEvent.Closed(1006, ""))
        round.await()
        assertEquals(42_000L, session.view.value.droppedAtMillis)
    }

    @Test
    fun anAddressPreferredAsTheOnlyOneIsTheOnlyOneARoundTries() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.silent }
        val (session, _) = session(transport, nameAddress = "10.9.9.9")
        session.preferAddress("https://100.88.0.1:8443", isOnly = true)
        session.runOnce()
        session.runOnce()
        assertEquals(listOf("https://100.88.0.1:8443", "https://100.88.0.1:8443"), transport.dialled.map { it.first })
        session.preferAddress("https://100.88.0.1:8443")
        session.runOnce()
        assertEquals(6, transport.dialled.size)
    }

    @Test
    fun aRoundBusyOnOtherAddressesGivesWayToTheOnlyAddressWithinASecond() = runTest {
        val over = "https://100.88.0.1:8443"
        val transport = FakeHubTransport { url -> if (url == over) FakeHubTransport.welcoming else emptyList() }
        val (session, _) = session(transport)
        session.start(backgroundScope)
        advanceTimeBy(3_000)
        assertEquals(listOf("https://192.168.100.1:8443"), transport.dialled.map { it.first })
        session.preferAddress(over, isOnly = true)
        advanceTimeBy(1_000)
        assertEquals(listOf("https://192.168.100.1:8443", over), transport.dialled.map { it.first })
        assertEquals(HubConnection.CONNECTED, session.view.value.connection)
        assertEquals(over, session.view.value.connectedAddress)
    }

    @Test
    fun aPreferredAddressIsTriedFirst() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.silent }
        val (session, _) = session(transport)
        session.preferAddress("https://hub.netbird.cloud:8443")
        session.runOnce()
        assertEquals("https://hub.netbird.cloud:8443", transport.dialled.first().first)
    }

    @Test
    fun aPendingBindingSpendsItsTicketAtTheFirstAddressThatAnswersThenSaysHelloThere() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.welcoming }
        transport.answers["https://100.72.4.1:8443" to "/api/channel/join"] = spent()
        val (session, store) = session(transport, binding = pending)
        assertEquals(HubConnection.PENDING, session.view.value.connection)
        served(session)
        advanceTimeBy(1_500)
        assertEquals(
            listOf("https://192.168.100.1:8443", "https://100.72.4.1:8443"),
            transport.posts.map { it.first },
        )
        assertEquals(emptyList<String>(), GoldenSchema.problems(transport.posts.last().third, "ChannelJoinRequest"))
        assertEquals("ticket-1", transport.posts.last().third["ticket"]!!.jsonPrimitive.content)
        val (address, socket, _) = transport.dialled.single()
        assertEquals("https://100.72.4.1:8443", address)
        assertEquals("c9", socket.sent("hello").single()["id"]!!.jsonPrimitive.content)
        assertEquals("t9", socket.sent("hello").single()["token"]!!.jsonPrimitive.content)
        val kept = store.get("b1")
        assertEquals(false, kept?.isPending)
        assertEquals("t9", kept?.token)
        assertEquals("c9", kept?.boundId)
        assertEquals(listOf("b1" to "c9"), joined)
        assertEquals(HubConnection.CONNECTED, session.view.value.connection)
    }

    @Test
    fun aHubReachableAtJoinTimeIsConnectedWithinTheFirstRound() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.welcoming }
        transport.answers["https://192.168.100.1:8443" to "/api/channel/join"] = spent()
        val (session, _) = session(transport, binding = pending)
        served(session)
        assertEquals(HubConnection.CONNECTED, session.view.value.connection)
    }

    @Test
    fun aPendingBindingStaysPendingWhileNoAddressAnswersAndDialsNothing() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.welcoming }
        val (session, store) = session(transport, binding = pending)
        assertEquals(5L, session.runOnce())
        assertEquals(HubConnection.PENDING, session.view.value.connection)
        assertEquals("hub_unreachable", session.view.value.lastError?.code)
        assertEquals(emptyList<Any>(), transport.dialled)
        assertEquals(pending, store.get("b1"))
    }

    @Test
    fun aPausedAdmissionKeepsTheTicketAndJoinsAgainAfterTheSecondsItNames() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.welcoming }
        transport.answers["https://192.168.100.1:8443" to "/api/channel/join"] =
            ChannelResult.Refused("admission_paused", JsonObject(mapOf("retry_after_s" to JsonPrimitive(42))))
        val (session, store) = session(transport, binding = pending)
        assertEquals(42L, session.runOnce())
        assertEquals(HubConnection.PENDING, session.view.value.connection)
        assertEquals("admission_paused", session.view.value.lastError?.code)
        assertEquals(false, session.view.value.isJoinRefused)
        assertEquals(pending, store.get("b1"))
        transport.answers["https://192.168.100.1:8443" to "/api/channel/join"] = spent()
        served(session)
        assertEquals(2, transport.posts.size)
        assertEquals("t9", store.get("b1")?.token)
    }

    @Test
    fun theStateNamesTheWayInAndWhetherThePanelMayOpen() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.welcoming }
        val (session, _) = session(transport)
        served(session)
        assertEquals("", session.view.value.reachedThrough)
        val (_, _, events) = transport.dialled.single()
        events.trySend(
            ChannelSocketEvent.Text(
                """{"type":"state","hash":"h2","is_panel_allowed":true,"reached_through":"relay"}""",
            ),
        )
        runCurrent()
        assertEquals("relay", session.view.value.reachedThrough)
        assertEquals(true, session.view.value.isPanelAllowed)
    }

    @Test
    fun aConnectStreamCarriesBytesBothWaysAndOpensWithAWindow() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.welcoming }
        val (session, _) = session(transport)
        served(session)
        val (_, socket, _) = transport.dialled.single()
        val stream = (session.openConnect(ChannelFrames.args("is_panel" to true)) as ChannelResult.Ok).value
        val open = socket.sent("open").single()
        assertEquals("connect", open["kind"]!!.jsonPrimitive.content)
        assertEquals(true, open["is_panel"]!!.jsonPrimitive.boolean)
        assertEquals(stream.id, socket.sent("credit").single()["stream"]!!.jsonPrimitive.content.toInt())
    }

    @Test
    fun aConnectStreamWithNoSocketIsUnreachable() = runTest {
        val (session, _) = session(FakeHubTransport { FakeHubTransport.welcoming })
        assertEquals(
            "hub_unreachable",
            (session.openConnect(ChannelFrames.args("id" to "p1")) as ChannelResult.Refused).code,
        )
    }

    @Test
    fun aRefusedTicketIsDownWithItsCodeAndNoRoundRunsAfter() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.welcoming }
        transport.answers["https://192.168.100.1:8443" to "/api/channel/join"] = ChannelResult.refused("ticket_spent")
        val (session, store) = session(transport, binding = pending)
        session.runOnce()
        assertEquals(HubConnection.DOWN, session.view.value.connection)
        assertEquals("ticket_spent", session.view.value.lastError?.code)
        assertEquals(true, session.view.value.isJoinRefused)
        assertEquals(2L, session.runOnce())
        assertEquals(false, session.refresh())
        assertEquals(1, transport.posts.size)
        assertEquals(emptyList<Any>(), transport.dialled)
        assertEquals(pending, store.get("b1"))
    }
}
