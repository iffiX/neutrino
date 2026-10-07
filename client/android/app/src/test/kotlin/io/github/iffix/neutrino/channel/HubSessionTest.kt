package io.github.iffix.neutrino.channel

import io.github.iffix.neutrino.CLIENT_CONNECT_TIMEOUT_S
import io.github.iffix.neutrino.CLIENT_PING_INTERVAL_S
import io.github.iffix.neutrino.CLIENT_WS_CLOSE_NORMAL
import io.github.iffix.neutrino.GoldenSchema
import io.github.iffix.neutrino.binding.BindingStore
import io.github.iffix.neutrino.binding.FakeSecretSealer
import io.github.iffix.neutrino.binding.HubBinding
import io.github.iffix.neutrino.forward.PortForwardUdpRelay
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.InetSocketAddress
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.async
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.currentTime
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
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
    private val lanUrl = "https://192.168.100.1:8443"
    private val directUrl = "https://100.72.4.1:8443"
    private val lanNetwork = ChannelLocalNetwork(InetAddress.getByName("192.168.100.7"), 24)
    private val easytierRoute = ChannelOverlayRoute(
        "https://10.126.126.1:8443",
        "easytier",
        ChannelLocalNetwork(InetAddress.getByName("10.126.126.7"), 24),
    )

    private fun session(
        transport: FakeHubTransport,
        nameAddress: String? = null,
        binding: HubBinding = Samples.binding,
        local: List<ChannelLocalNetwork> = emptyList(),
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
            localNetworks = { local },
            nanoClock = { 0L },
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
        val socket = transport.greeted().second
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
        val (_, socket, events) = transport.greeted()
        events.trySend(
            ChannelSocketEvent.Text(
                """{"type":"state","hash":"h9","urls":["https://10.0.0.1:8443"],
                   "overlays":[{"provider":"easytier","mode":"console","config_server":"tcp://c/t"}],
                   "services":[{"id":"s","type":"port","title":"SSH","payload":{"host":"h","port":22},"source":"declared"}]}""",
            ),
        )
        runCurrent()
        assertEquals(listOf("https://10.0.0.1:8443"), store.get("b1")?.gatewayUrls)
        assertEquals("easytier", store.get("b1")?.overlays?.single()?.provider)
        assertEquals("SSH", session.view.value.services.single().title)
        assertEquals("h9", socket.sent("report").last()["state_hash"]!!.jsonPrimitive.content)
    }

    @Test
    fun aReportGoesUpEveryThirtySeconds() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.welcoming }
        val (session, _) = session(transport)
        served(session)
        val socket = transport.greeted().second
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
    fun aRoundDialsEveryAddressAtOnce() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.silent }
        val (session, _) = session(transport, nameAddress = "10.9.9.9")
        session.runOnce()
        assertEquals(
            listOf("https://10.9.9.9:8443", "https://192.168.100.1:8443", "https://100.72.4.1:8443"),
            transport.dialled.map { it.first },
        )
        assertEquals(0L, currentTime)
    }

    @Test
    fun aRoundWhoseFirstAddressHangsConnectsThroughTheThirdWithinOneConnectTime() = runTest {
        val transport = FakeHubTransport { url ->
            when {
                url.contains("10.9.9.9") -> FakeHubTransport.hanging
                url.contains("192.168.100.1") -> FakeHubTransport.silent
                else -> FakeHubTransport.welcoming
            }
        }
        val (session, _) = session(transport, nameAddress = "10.9.9.9")
        served(session)
        assertEquals(HubConnection.CONNECTED, session.view.value.connection)
        assertEquals("https://100.72.4.1:8443", session.view.value.connectedAddress)
        assertTrue(currentTime < CLIENT_CONNECT_TIMEOUT_S * 1000)
        assertEquals(CLIENT_WS_CLOSE_NORMAL, transport.dialled.first().second.closedWith)
    }

    @Test
    fun aRoundSendsOneHelloAndClosesTheOtherSocketsBeforeAny() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.welcoming }
        val (session, _) = session(transport, nameAddress = "10.9.9.9")
        served(session)
        assertEquals(3, transport.dialled.size)
        assertEquals(1, transport.dialled.sumOf { it.second.sent("hello").size })
        val (winner, losers) = transport.dialled.partition { it.second.sent("hello").isNotEmpty() }
        assertEquals(null, winner.single().second.closedWith)
        assertEquals(winner.single().first, session.view.value.connectedAddress)
        for ((_, socket, _) in losers) {
            assertEquals(CLIENT_WS_CLOSE_NORMAL, socket.closedWith)
            assertEquals(emptyList<Any>(), socket.texts)
        }
    }

    @Test
    fun theOpenSocketPingsAndEachPongSetsTheRoundTrip() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.welcoming }
        val (session, _) = session(transport)
        val round = served(session)
        val (_, socket, events) = transport.greeted()
        assertEquals(1, socket.pings)
        assertEquals(null, session.view.value.rttMs)
        events.trySend(ChannelSocketEvent.Pong(12))
        runCurrent()
        assertEquals(12L, session.view.value.rttMs)
        advanceTimeBy(CLIENT_PING_INTERVAL_S * 1000 + 1)
        assertEquals(2, socket.pings)
        events.trySend(ChannelSocketEvent.Pong(7))
        runCurrent()
        assertEquals(7L, session.view.value.rttMs)
        events.trySend(ChannelSocketEvent.Closed(1006, ""))
        round.await()
        assertEquals(null, session.view.value.rttMs)
    }

    @Test
    fun aReconnectStartsFromTheFirstAddressNotTheOneThatWorkedLast() = runTest {
        var isNearUp = false
        val transport = FakeHubTransport { url ->
            if (url.contains("192.168.100.1") && !isNearUp) FakeHubTransport.silent else FakeHubTransport.welcoming
        }
        val (session, store) = session(transport)
        val round = backgroundScope.async { session.runOnce() }
        advanceTimeBy(60_000)
        assertEquals(HubConnection.CONNECTED, session.view.value.connection)
        assertEquals("https://100.72.4.1:8443", session.view.value.connectedAddress)
        assertEquals("https://100.72.4.1:8443", store.get("b1")?.gatewayUrl)
        isNearUp = true
        transport.greeted().third.trySend(ChannelSocketEvent.Closed(1006, ""))
        round.await()
        served(session)
        assertEquals(
            listOf(
                "https://192.168.100.1:8443",
                "https://100.72.4.1:8443",
                "https://192.168.100.1:8443",
                "https://100.72.4.1:8443",
            ),
            transport.dialled.map { it.first },
        )
        assertEquals("https://192.168.100.1:8443", session.view.value.connectedAddress)
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
        transport.greeted().third.trySend(ChannelSocketEvent.Closed(4010, "replaced"))
        assertEquals(2L, round.await())
        assertEquals(HubConnection.REPLACED, session.view.value.connection)
        assertEquals(2L, session.runOnce())
        val dialledOnce = transport.dialled.size
        session.reconnect()
        served(session)
        assertEquals(2 * dialledOnce, transport.dialled.size)
    }

    @Test
    fun aRefusedFrameOnAnOpenSocketIsARefusal() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.welcoming }
        val (session, _) = session(transport)
        val round = served(session)
        transport.greeted().third.trySend(
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
        transport.greeted().third.trySend(
            ChannelSocketEvent.Text(
                """{"type":"state","hash":"h","is_disabled":true,"services":[{"id":"s","type":"web","title":"t","payload":{},"source":"module"}]}""",
            ),
        )
        runCurrent()
        assertEquals(emptyList<ChannelServiceEntry>(), session.view.value.servicesOf("web"))
        assertEquals(HubConnection.DISABLED, session.view.value.connection)
        transport.greeted().third.trySend(
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
        val (_, socket, events) = transport.greeted()
        val material = backgroundScope.async { session.openService("ai-1") }
        runCurrent()
        val open = socket.sent("open").single()
        assertEquals("service", open["kind"]!!.jsonPrimitive.content)
        assertEquals("ai-1", open["id"]!!.jsonPrimitive.content)
        events.trySend(ChannelSocketEvent.Text("""{"type":"close","stream":1,"code":"","params":{"api_key":"k"}}"""))
        assertEquals("k", ((material.await() as ChannelResult.Ok).value["api_key"])!!.jsonPrimitive.content)
    }

    @Test
    fun thePanelsTokenIsTheCloseOfAServiceStreamNamingThePanel() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.welcoming }
        val (session, _) = session(transport)
        served(session)
        val (_, socket, events) = transport.greeted()
        val material = backgroundScope.async { session.openService(ChannelFrames.args("is_panel" to true)) }
        runCurrent()
        val open = socket.sent("open").single()
        assertEquals("service", open["kind"]!!.jsonPrimitive.content)
        assertEquals(true, open["is_panel"]!!.jsonPrimitive.boolean)
        assertEquals(null, open["id"])
        events.trySend(ChannelSocketEvent.Text("""{"type":"close","stream":1,"code":"","params":{"token":"t"}}"""))
        assertEquals("t", ((material.await() as ChannelResult.Ok).value["token"])!!.jsonPrimitive.content)
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
        transport.greeted().third.trySend(ChannelSocketEvent.Closed(1006, ""))
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
        val (_, socket, events) = transport.greeted()
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
        transport.greeted().third.trySend(
            ChannelSocketEvent.Text("""{"type":"state","hash":"h","is_disabled":true}"""),
        )
        runCurrent()
        assertEquals(false, session.refresh())
        transport.greeted().third.trySend(ChannelSocketEvent.Closed(4010, "replaced"))
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
        assertEquals(before + Samples.binding.storedUrls.size, transport.dialled.size)
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
        val dialledOnce = transport.dialled.size
        session.resume()
        runCurrent()
        assertEquals(dialledOnce, transport.dialled.size)
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
        transport.greeted().third.trySend(ChannelSocketEvent.Closed(1006, ""))
        round.await()
        assertEquals(42_000L, session.view.value.droppedAtMillis)
    }

    @Test
    fun aNetworkOnRunsARoundBesideTheChannelAndAWorseWinnerIsClosedBeforeAnyHello() = runTest {
        val hanging = mutableSetOf<String>()
        val transport = FakeHubTransport { url ->
            if (url in
                hanging
            ) {
                FakeHubTransport.hanging
            } else {
                FakeHubTransport.welcoming
            }
        }
        val (session, _) = session(transport, local = listOf(lanNetwork))
        served(session)
        assertEquals(lanUrl, session.view.value.connectedAddress)
        hanging += listOf(lanUrl, directUrl)
        session.overlayChanged(easytierRoute)
        runCurrent()
        val (_, over, _) = transport.dialled.single { it.first == easytierRoute.url }
        assertEquals(CLIENT_WS_CLOSE_NORMAL, over.closedWith)
        assertEquals(emptyList<Any>(), over.texts)
        assertEquals(1, transport.dialled.sumOf { it.second.sent("hello").size })
        assertEquals(HubConnection.CONNECTED, session.view.value.connection)
        assertEquals(lanUrl, session.view.value.connectedAddress)
    }

    @Test
    fun aBetterPathTakesTheChannelAndTheOldSocketsReplacedCloseIsNotShown() = runTest {
        val hanging = mutableSetOf(lanUrl, directUrl)
        val transport = FakeHubTransport { url ->
            if (url in
                hanging
            ) {
                FakeHubTransport.hanging
            } else {
                FakeHubTransport.welcoming
            }
        }
        val (session, store) = session(transport, local = listOf(lanNetwork))
        session.overlayChanged(easytierRoute)
        val round = served(session)
        assertEquals(easytierRoute.url, session.view.value.connectedAddress)
        val (_, old, oldEvents) = transport.greeted()
        hanging.clear()
        hanging += easytierRoute.url
        session.networkChanged()
        runCurrent()
        val (address, moved, _) = transport.greeted()
        assertEquals(lanUrl, address)
        assertEquals(1, moved.sent("hello").size)
        assertEquals(2, transport.dialled.sumOf { it.second.sent("hello").size })
        assertEquals(CLIENT_WS_CLOSE_NORMAL, old.closedWith)
        oldEvents.trySend(ChannelSocketEvent.Closed(4010, "replaced"))
        runCurrent()
        assertEquals(HubConnection.CONNECTED, session.view.value.connection)
        assertEquals(lanUrl, session.view.value.connectedAddress)
        assertEquals(lanUrl, store.get("b1")?.gatewayUrl)
        assertEquals(false, round.isCompleted)
    }

    @Test
    fun aReplacedCloseThatComesBeforeTheMoveIsNotShownEither() = runTest {
        val hanging = mutableSetOf(lanUrl, directUrl)
        val transport = FakeHubTransport { url ->
            when (url) {
                in hanging -> FakeHubTransport.hanging
                lanUrl -> listOf(ChannelSocketEvent.Opened)
                else -> FakeHubTransport.welcoming
            }
        }
        val (session, _) = session(transport, local = listOf(lanNetwork))
        session.overlayChanged(easytierRoute)
        served(session)
        val (_, _, oldEvents) = transport.greeted()
        hanging.clear()
        hanging += easytierRoute.url
        session.networkChanged()
        runCurrent()
        val (_, _, lanEvents) = transport.dialled.last { it.first == lanUrl }
        oldEvents.trySend(ChannelSocketEvent.Closed(4010, "replaced"))
        runCurrent()
        lanEvents.trySend(FakeHubTransport.welcoming.last())
        runCurrent()
        assertEquals(HubConnection.CONNECTED, session.view.value.connection)
        assertEquals(lanUrl, session.view.value.connectedAddress)
    }

    @Test
    fun aWinnerOnTheSamePathThatOpenedNoFasterLeavesTheChannel() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.welcoming }
        val store = BindingStore(folder.root.resolve("b.sealed"), FakeSecretSealer())
        store.put(Samples.binding)
        val session = HubSession(
            "b1",
            store,
            transport,
            Samples.machine,
            { null },
            { _, _ -> },
            localNetworks = { listOf(lanNetwork) },
            nanoClock = { 0L },
        )
        served(session)
        session.networkChanged()
        runCurrent()
        assertEquals(1, transport.dialled.sumOf { it.second.sent("hello").size })
        assertEquals(lanUrl, session.view.value.connectedAddress)
    }

    @Test
    fun aWinnerOnTheSamePathThatOpenedFasterTakesTheChannel() = runTest {
        var now = 0L
        var step = 500L
        val transport = FakeHubTransport { FakeHubTransport.welcoming }
        val store = BindingStore(folder.root.resolve("b.sealed"), FakeSecretSealer())
        store.put(Samples.binding)
        val session = HubSession(
            "b1",
            store,
            transport,
            Samples.machine,
            { null },
            { _, _ -> },
            localNetworks = { listOf(lanNetwork) },
            nanoClock = {
                now += step
                now
            },
        )
        served(session)
        step = 100L
        session.networkChanged()
        runCurrent()
        assertEquals(2, transport.dialled.sumOf { it.second.sent("hello").size })
        assertEquals(lanUrl, session.view.value.connectedAddress)
        assertEquals(HubConnection.CONNECTED, session.view.value.connection)
    }

    @Test
    fun aStateNamingOtherAddressesRunsARound() = runTest {
        val transport = FakeHubTransport { url ->
            if (url ==
                "https://10.0.0.9:8443"
            ) {
                FakeHubTransport.hanging
            } else {
                FakeHubTransport.welcoming
            }
        }
        val (session, _) = session(transport)
        served(session)
        val (_, _, events) = transport.greeted()
        events.trySend(
            ChannelSocketEvent.Text(
                """{"type":"state","hash":"h","urls":["$lanUrl","$directUrl","https://10.0.0.9:8443"]}""",
            ),
        )
        runCurrent()
        assertTrue(transport.dialled.any { it.first == "https://10.0.0.9:8443" })
        val dialled = transport.dialled.size
        events.trySend(
            ChannelSocketEvent.Text(
                """{"type":"state","hash":"h2","urls":["$lanUrl","$directUrl","https://10.0.0.9:8443"]}""",
            ),
        )
        runCurrent()
        assertEquals(dialled, transport.dialled.size)
    }

    @Test
    fun aConnectivityChangeRunsARoundWhetherConnectedOrNot() = runTest {
        var isUp = false
        val transport = FakeHubTransport { if (isUp) FakeHubTransport.welcoming else FakeHubTransport.silent }
        val (session, _) = session(transport)
        session.start(backgroundScope)
        runCurrent()
        assertEquals(HubConnection.DOWN, session.view.value.connection)
        val before = transport.dialled.size
        isUp = true
        session.networkChanged()
        runCurrent()
        assertTrue(transport.dialled.size > before)
        assertEquals(HubConnection.CONNECTED, session.view.value.connection)
        val connected = transport.dialled.size
        session.networkChanged()
        runCurrent()
        assertTrue(transport.dialled.size > connected)
        assertEquals(1, transport.dialled.sumOf { it.second.sent("hello").size })
    }

    @Test
    fun aReplacedHubRunsNoRoundOnANetworkChange() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.welcoming }
        val (session, _) = session(transport)
        val round = served(session)
        transport.greeted().third.trySend(ChannelSocketEvent.Closed(4010, "replaced"))
        round.await()
        val before = transport.dialled.size
        session.networkChanged()
        runCurrent()
        assertEquals(before, transport.dialled.size)
        assertEquals(HubConnection.REPLACED, session.view.value.connection)
    }

    @Test
    fun theVirtualNetworksAddressIsACandidateOfEveryRound() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.silent }
        val (session, _) = session(transport)
        session.overlayChanged(easytierRoute)
        session.runOnce()
        assertTrue(transport.dialled.any { it.first == easytierRoute.url })
        session.overlayChanged(null)
        val before = transport.dialled.size
        session.runOnce()
        assertTrue(transport.dialled.drop(before).none { it.first == easytierRoute.url })
    }

    @Test
    fun aPendingBindingSpendsItsTicketAtTheRoundsSocketThenSaysHelloThere() = runTest {
        val transport = FakeHubTransport { url ->
            if (url.contains("192.168.100.1")) FakeHubTransport.hanging else FakeHubTransport.welcoming
        }
        transport.answers["https://100.72.4.1:8443" to "/api/channel/join"] = spent()
        val (session, store) = session(transport, binding = pending)
        assertEquals(HubConnection.PENDING, session.view.value.connection)
        served(session)
        assertEquals(listOf("https://100.72.4.1:8443"), transport.posts.map { it.first })
        assertEquals(emptyList<String>(), GoldenSchema.problems(transport.posts.last().third, "ChannelJoinRequest"))
        assertEquals("ticket-1", transport.posts.last().third["ticket"]!!.jsonPrimitive.content)
        val (address, socket, _) = transport.greeted()
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
    fun aPendingBindingStaysPendingWhileNoAddressAnswersAndSpendsNothing() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.silent }
        val (session, store) = session(transport, binding = pending)
        assertEquals(5L, session.runOnce())
        assertEquals(HubConnection.PENDING, session.view.value.connection)
        assertEquals("hub_unreachable", session.view.value.lastError?.code)
        assertEquals(emptyList<Any>(), transport.posts)
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
        val (_, _, events) = transport.greeted()
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
        val (_, socket, _) = transport.greeted()
        val stream = (session.openConnect(ChannelFrames.args("is_panel" to true)) as ChannelResult.Ok).value
        val open = socket.sent("open").single()
        assertEquals("connect", open["kind"]!!.jsonPrimitive.content)
        assertEquals(true, open["is_panel"]!!.jsonPrimitive.boolean)
        assertEquals(stream.id, socket.sent("credit").single()["stream"]!!.jsonPrimitive.content.toInt())
    }

    @Test
    fun aUdpStreamClosedWithACodeReachesItsForward() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.welcoming }
        val (session, _) = session(transport)
        served(session)
        val (_, socket, events) = transport.greeted()
        val refusals = LinkedBlockingQueue<String>()
        var now = 0L
        val relay = PortForwardUdpRelay(
            "b1/dns_udp",
            { session.openConnect(ChannelFrames.args("id" to "dns_udp")) },
            0,
            { refusal, isEnded -> refusals.put("${refusal.code} $isEnded") },
        ) { now }
        val port = relay.start()
        DatagramSocket().use { program ->
            val query = DatagramPacket(byteArrayOf(1, 2, 3), 3, InetSocketAddress("127.0.0.1", port))
            val first = socket.sent("open").single()["stream"]!!.jsonPrimitive.int
            events.trySend(ChannelSocketEvent.Text("""{"type":"credit","stream":$first,"bytes":65536}"""))
            runCurrent()
            program.send(query)
            waitFor { synchronized(socket) { socket.binaries.isNotEmpty() } }
            events.trySend(
                ChannelSocketEvent.Text(
                    """{"type":"close","stream":$first,"code":"port_not_published","params":{"port":5353}}""",
                ),
            )
            runCurrent()
            assertEquals("port_not_published false", refusals.poll(30, TimeUnit.SECONDS))
            assertTrue(relay.isActive)
            now += 1000
            program.send(query)
            waitFor { socket.sent("open").size == 2 }
            val second = socket.sent("open")[1]["stream"]!!.jsonPrimitive.int
            events.trySend(
                ChannelSocketEvent.Text(
                    """{"type":"close","stream":$second,"code":"service_unknown","params":{"service_id":"dns_udp"}}""",
                ),
            )
            runCurrent()
            assertEquals("service_unknown false", refusals.poll(30, TimeUnit.SECONDS))
            assertTrue(relay.isActive)
        }
        relay.close()
    }

    private fun waitFor(condition: () -> Boolean) {
        val deadline = System.currentTimeMillis() + 30_000
        while (!condition()) {
            assertTrue("the condition did not hold in 30 s", System.currentTimeMillis() < deadline)
            Thread.sleep(10)
        }
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
        assertTrue(transport.dialled.all { it.second.closedWith != null && it.second.texts.isEmpty() })
        assertEquals(pending, store.get("b1"))
    }
}
