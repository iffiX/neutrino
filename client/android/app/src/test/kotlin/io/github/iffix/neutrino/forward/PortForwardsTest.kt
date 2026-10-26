package io.github.iffix.neutrino.forward

import io.github.iffix.neutrino.FakeSharedPreferences
import io.github.iffix.neutrino.binding.HubBinding
import io.github.iffix.neutrino.channel.ChannelApp
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.ChannelServiceEntry
import io.github.iffix.neutrino.channel.HubConnection
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.transport.TransportForwardEnd
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class PortForwardsTest {
    private val busy = mutableSetOf<Int>()
    private val table = LocalPortTable(FakeSharedPreferences()) { port, _, _ -> port !in busy }
    private val forwarder = FakeForwarder()
    private val asked = mutableListOf<Map<String, JsonElement>>()
    private var material: ChannelResult<JsonObject> = ChannelResult.Ok(
        JsonObject(mapOf("token" to JsonPrimitive("t-1_x"))),
    )
    private val opened = mutableListOf<String>()

    private val web = entry("gitea_d1_web", "web", payload("url" to "http://10.0.0.5:3000/explore?tab=1"), 27311)
    private val ssh = entry("gitea_d1_ssh", "port", payload("host" to "10.0.0.5", "port" to 22), 30418)
    private val sshKey = entry("ssh_server_d1_iffi", "ssh", payload("port" to 2201), 24555, appId = "ssh_server_d1")
    private val app = ChannelApp("gitea_d1", "Gitea", "module", "d1", "lab", "gitea.lab.localhost")
    private val hub = HubView(
        binding = HubBinding(id = "b1", hubId = "hub-1", gatewayUrl = "tcp://192.168.100.1:8443", token = "t"),
        connection = HubConnection.CONNECTED,
        services = listOf(web, ssh, sshKey),
        apps = listOf(app, ChannelApp("ssh_server_d1", "SSH", "module", "d1", "lab", "ssh.lab.localhost")),
        isPanelAllowed = true,
    )

    private fun entry(id: String, type: String, payload: JsonObject, port: Int, appId: String = "gitea_d1") =
        ChannelServiceEntry(
            id,
            type,
            "Gitea",
            payload,
            source = "module",
            appId = appId,
            name = id.substringAfterLast('_'),
            localPort = port,
        )

    private fun payload(vararg fields: Pair<String, Any>) = JsonObject(
        fields.associate { (name, value) ->
            name to
                if (value is Int) JsonPrimitive(value) else JsonPrimitive(value.toString())
        },
    )

    private fun kotlinx.coroutines.test.TestScope.forwards(host: String? = null) = PortForwards(
        material = { _, args ->
            asked += args
            material
        },
        forwarder = forwarder,
        scope = backgroundScope,
        table = table,
        loopbackHost = host,
        log = {},
    )

    @Test
    fun useForwardsEveryEntry() = runTest {
        val forwards = forwards()
        forwards.use(hub, app) { opened += it }
        runCurrent()
        assertEquals(listOf(27311 to "tcp", 30418 to "tcp"), forwarder.listening.map { it.second to it.third })
        assertEquals(
            listOf("gitea_d1_web", "gitea_d1_ssh"),
            forwarder.listening.map {
                it.fourth["id"]!!.jsonPrimitive.content
            },
        )
        assertEquals(listOf("http://gitea.lab.localhost:27311/explore?tab=1"), opened)
        assertTrue(forwards.rows.value["b1/gitea_d1"]!!.isInUse)
        assertTrue(asked.isEmpty())
    }

    @Test
    fun anSshEntryIsLeftOutOnAPhone() = runTest {
        val forwards = forwards()
        forwards.use(hub, hub.apps[1]) { opened += it }
        runCurrent()
        assertTrue(forwarder.listening.isEmpty())
        assertTrue(opened.isEmpty())
    }

    @Test
    fun aTokenPageOpensWithAFreshTokenAtEachUse() = runTest {
        val tokened = web.copy(payload = payload("url" to "http://10.0.0.5:8000/"))
            .let { it.copy(payload = JsonObject(it.payload + ("is_token_required" to JsonPrimitive(true)))) }
        val forwards = forwards()
        val withToken = hub.copy(services = listOf(tokened))
        forwards.use(withToken, app) { opened += it }
        runCurrent()
        forwards.use(withToken, app) { opened += it }
        runCurrent()
        assertEquals(List(2) { "http://gitea.lab.localhost:27311/?tkn=t-1_x" }, opened)
        assertEquals(1, forwarder.listening.size)
        assertEquals(2, asked.size)
        assertEquals("gitea_d1_web", asked.first()["id"]!!.jsonPrimitive.content)
    }

    @Test
    fun onAPhoneWhoseBrowserResolvesNoLocalhostNameThePageOpensAtTheLoopback() = runTest {
        val forwards = forwards(host = "127.0.0.1")
        forwards.use(hub, app) { opened += it }
        runCurrent()
        assertEquals(listOf("http://127.0.0.1:27311/explore?tab=1"), opened)
    }

    @Test
    fun aHeldNumberFailsAlone() = runTest {
        busy += 30418
        val forwards = forwards()
        forwards.use(hub, app) { opened += it }
        runCurrent()
        val row = forwards.rows.value["b1/gitea_d1"]!!
        assertEquals("port_taken", row.error?.code)
        assertEquals("30418", row.error?.wordParams?.get("port"))
        assertEquals(listOf(27311), forwarder.listening.map { it.second })
        assertTrue(row.isInUse)
    }

    @Test
    fun theTransportsRefusalOfAListenerIsTheRowsCode() = runTest {
        forwarder.refusal = ChannelResult.refused("port_taken", "port" to "27311")
        val forwards = forwards()
        forwards.use(hub, app) { opened += it }
        runCurrent()
        assertEquals("port_taken", forwards.rows.value["b1/gitea_d1"]?.error?.code)
        assertTrue(opened.isEmpty())
    }

    @Test
    fun stopEndsEveryForwardOfTheApp() = runTest {
        val forwards = forwards()
        forwards.use(hub, app) {}
        runCurrent()
        forwards.stop("b1", "gitea_d1")
        assertEquals(PortForwardJob.DISCONNECTING, forwards.rows.value["b1/gitea_d1"]?.job)
        runCurrent()
        assertEquals(listOf(27311 to "tcp", 30418 to "tcp"), forwarder.stopped)
        assertNull(forwards.rows.value["b1/gitea_d1"])
    }

    @Test
    fun configureIsRefusedWhileTheAppIsInUseAndKeptOtherwise() = runTest {
        val forwards = forwards()
        assertEquals(
            ChannelResult.Ok(Unit),
            forwards.configure(listOf(hub), "b1", "gitea_d1", mapOf("gitea_d1_web" to 28080)),
        )
        assertEquals(28080, forwards.portOf("b1", web))
        forwards.use(hub, app) {}
        runCurrent()
        assertEquals(28080, forwarder.listening.first().second)
        val refused = forwards.configure(listOf(hub), "b1", "gitea_d1", mapOf("gitea_d1_web" to null))
        assertEquals("disconnect_first", (refused as ChannelResult.Refused).code)
    }

    @Test
    fun configureRefusesANumberAnotherEntryHoldsAsItsHubNumber() = runTest {
        val forwards = forwards()
        val refused = forwards.configure(listOf(hub), "b1", "gitea_d1", mapOf("gitea_d1_web" to 30418))
        assertEquals("port_taken", (refused as ChannelResult.Refused).code)
    }

    @Test
    fun withdrawnEntriesStop() = runTest {
        val forwards = forwards()
        forwards.use(hub, app) {}
        runCurrent()
        forwards.take(listOf(hub.copy(services = listOf(web))))
        runCurrent()
        assertEquals(listOf(30418 to "tcp"), forwarder.stopped)
        forwards.take(emptyList())
        runCurrent()
        assertEquals(listOf(30418 to "tcp", 27311 to "tcp"), forwarder.stopped)
    }

    @Test
    fun panelSignsIn() = runTest {
        val forwards = forwards()
        forwards.openPanel("b1", "hub-1") { opened += it }
        runCurrent()
        assertEquals(listOf("http://panel-hub-1.localhost:20000/?tkn=t-1_x"), opened)
        assertEquals(JsonPrimitive(true), forwarder.listening.single().fourth["is_panel"])
        assertEquals(20000, forwards.rows.value["b1/#panel"]?.localPort)
        assertEquals(JsonPrimitive(true), asked.single()["is_panel"])
    }

    @Test
    fun aRefusedPanelTokenOpensNothing() = runTest {
        material = ChannelResult.refused("permission_denied", "kind" to "panel")
        val forwards = forwards()
        forwards.openPanel("b1", "hub-1") { opened += it }
        runCurrent()
        assertTrue(opened.isEmpty())
        assertEquals("permission_denied", forwards.rows.value["b1/#panel"]?.error?.code)
        assertTrue(forwarder.listening.isEmpty())
    }

    @Test
    fun aRemoteDesktopsForwardIsHeldAtAPickUntilItsViewerCloses() = runTest {
        val forwards = forwards()
        var bound: ChannelResult<Int>? = null
        backgroundScope.launch { bound = forwards.hold("b1", "rdp_d1") }
        runCurrent()
        assertEquals(ChannelResult.Ok(20000), bound)
        forwards.release("b1", "rdp_d1")
        runCurrent()
        assertEquals(listOf(20000 to "tcp"), forwarder.stopped)
    }

    @Test
    fun aUdpForwardTheHubEndedIsStartedAgainWhileItsAppIsInUse() = runTest {
        val udp =
            entry(
                "game_d1_7777_udp",
                "port",
                payload("host" to "h", "port" to 7777, "protocol" to "udp"),
                25001,
                appId = "game_d1",
            )
        val game = ChannelApp("game_d1", "game", "manual", "d1", "lab", "game.lab.localhost")
        val withUdp = hub.copy(services = listOf(udp), apps = listOf(game))
        val forwards = forwards()
        val ends = MutableSharedFlow<TransportForwardEnd>(extraBufferCapacity = 4)
        forwards.follow(MutableStateFlow(listOf(withUdp)), ends)
        forwards.use(withUdp, game) {}
        runCurrent()
        assertEquals(listOf(25001 to "udp"), forwarder.listening.map { it.second to it.third })
        ends.emit(
            TransportForwardEnd("127.0.0.1:25001", "udp", ChannelResult.refused("agent_offline", "device" to "lab")),
        )
        runCurrent()
        assertEquals("agent_offline", forwards.rows.value["b1/game_d1"]?.error?.code)
        advanceTimeBy(1500)
        runCurrent()
        assertEquals(2, forwarder.listening.size)
        assertFalse(forwarder.listening.isEmpty())
    }

    /** A forwarder that records each listener and answers with [refusal] when one is set. */
    private class FakeForwarder : LocalForwarder {
        val listening = mutableListOf<Quad>()
        val stopped = mutableListOf<Pair<Int, String>>()
        var refusal: ChannelResult.Refused? = null

        override suspend fun start(
            bindingId: String,
            port: Int,
            protocol: String,
            open: JsonObject,
        ): ChannelResult<Int> {
            refusal?.let { return it }
            listening += Quad(bindingId, port, protocol, open)
            return ChannelResult.Ok(port)
        }

        override suspend fun stop(port: Int, protocol: String) {
            stopped += port to protocol
        }
    }

    private data class Quad(val first: String, val second: Int, val third: String, val fourth: JsonObject)
}
