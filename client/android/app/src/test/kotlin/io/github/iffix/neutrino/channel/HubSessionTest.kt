package io.github.iffix.neutrino.channel

import io.github.iffix.neutrino.binding.BindingStore
import io.github.iffix.neutrino.binding.FakeSecretSealer
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.async
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
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

    private fun session(transport: FakeHubTransport, nameAddress: String? = null): Pair<HubSession, BindingStore> {
        val store = BindingStore(folder.root.resolve("b.sealed"), FakeSecretSealer())
        store.put(Samples.binding)
        val session = HubSession("b1", store, transport, Samples.machine, { nameAddress }, { unbound += it })
        return session to store
    }

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
        assertEquals(HubConnection.UNBOUND, session.view.value.connection)
        assertEquals(2L, session.runOnce())
    }

    @Test
    fun aSocketAnotherReplacedWaitsForAPerson() = runTest {
        val transport = FakeHubTransport { FakeHubTransport.welcoming }
        val (session, _) = session(transport)
        val round = served(session)
        transport.dialled.single().third.trySend(ChannelSocketEvent.Closed(4010, "replaced"))
        assertEquals(5L, round.await())
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
        assertEquals("client_disabled", session.view.value.lastError?.code)
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
}
