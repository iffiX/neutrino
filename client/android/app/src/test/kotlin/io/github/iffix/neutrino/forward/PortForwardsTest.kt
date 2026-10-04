package io.github.iffix.neutrino.forward

import io.github.iffix.neutrino.FakeSharedPreferences
import io.github.iffix.neutrino.binding.HubBinding
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.ChannelServiceEntry
import io.github.iffix.neutrino.channel.ChannelStream
import io.github.iffix.neutrino.channel.FakeConnectHub
import io.github.iffix.neutrino.channel.HubConnection
import io.github.iffix.neutrino.channel.HubView
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class PortForwardsTest {
    private val hub = FakeConnectHub()
    private val table = LocalPortTable(FakeSharedPreferences(), isFree = ::isFree)
    private val opened = mutableListOf<Pair<String, Map<String, JsonElement>>>()
    private val streams: (String, Map<String, JsonElement>) -> ChannelResult<ChannelStream> = { bindingId, args ->
        synchronized(opened) { opened += bindingId to args }
        hub.open(args)
    }
    private val noMaterial: suspend (String, String) -> ChannelResult<JsonObject> = { _, _ ->
        ChannelResult.Ok(JsonObject(emptyMap()))
    }

    @Test
    fun connectIsAJobUntilTheLoopbackListensAndEachConnectionIsAConnectStream() = runTest {
        val forwards = PortForwards(noMaterial, streams, backgroundScope, table)
        forwards.connect("b1", "p1", 30080)
        assertEquals(PortForwardJob.FORWARDING, forwards.rows.value["b1/p1"]?.job)
        runCurrent()
        val row = forwards.rows.value.getValue("b1/p1")
        assertNull(row.job)
        assertTrue(row.isForwarded)
        assertEquals("ping", exchange(row.localPort, "ping"))
        assertEquals(listOf("b1"), opened.map { it.first })
        assertEquals("p1", opened.single().second["id"]?.jsonPrimitive?.content)
        forwards.stopAll()
    }

    @Test
    fun aSecondPressWhileTheJobRunsIsDropped() = runTest {
        var made = 0
        val forwards = PortForwards(noMaterial, streams, backgroundScope, table) { name, open, local ->
            made += 1
            PortForwardRelay(name, open, local)
        }
        forwards.connect("b1", "p1", 30080)
        forwards.connect("b1", "p1", 30080)
        runCurrent()
        assertEquals(1, made)
        forwards.stopAll()
    }

    @Test
    fun disconnectIsAJobThenTheRowGoes() = runTest {
        val forwards = PortForwards(noMaterial, streams, backgroundScope, table)
        forwards.connect("b1", "p1", 30080)
        runCurrent()
        forwards.disconnect("b1", "p1")
        assertEquals(PortForwardJob.DISCONNECTING, forwards.rows.value["b1/p1"]?.job)
        runCurrent()
        assertNull(forwards.rows.value["b1/p1"])
    }

    @Test
    fun aFailedBindWritesForwardFailedUntilARefresh() = runTest {
        val forwards = PortForwards(noMaterial, streams, backgroundScope, table) { name, open, _ ->
            FailingRelay(name, open)
        }
        forwards.connect("b1", "p1", 30080)
        runCurrent()
        assertEquals("forward_failed", forwards.rows.value["b1/p1"]?.error?.code)
        forwards.clearErrors()
        assertNull(forwards.rows.value["b1/p1"])
    }

    @Test
    fun openForwardsTakesTheTokenAndOpensTheEntrysOwnLocalhostName() = runTest {
        val answer = CompletableDeferred<ChannelResult<JsonObject>>()
        val forwards = PortForwards({ _, _ -> answer.await() }, streams, backgroundScope, table)
        val pages = mutableListOf<String>()
        forwards.open("b1", "vscode-argon_iffi.1", "http://192.168.10.20:31001/", true, pages::add)
        runCurrent()
        assertEquals(PortForwardJob.OPENING, forwards.rows.value["b1/vscode-argon_iffi.1"]?.job)
        answer.complete(ChannelResult.Ok(JsonObject(mapOf("token" to JsonPrimitive("a b")))))
        runCurrent()
        val row = forwards.rows.value.getValue("b1/vscode-argon_iffi.1")
        assertEquals(31001, row.localPort)
        assertEquals(listOf("http://vscode-argon-iffi-1.localhost:31001/?tkn=a+b"), pages)
        assertNull(row.job)
        assertEquals("GET / HTTP/1.1\r\n", exchange(row.localPort, "GET / HTTP/1.1\r\n"))
        assertEquals("vscode-argon_iffi.1", opened.single().second["id"]?.jsonPrimitive?.content)
        forwards.stopAll()
    }

    @Test
    fun openWithoutATokenKeepsTheSchemeAndPathAndReadsNoMaterial() = runTest {
        var asked = 0
        val forwards = PortForwards({ _, _ ->
            asked += 1
            ChannelResult.Ok(JsonObject(emptyMap()))
        }, streams, backgroundScope, table)
        val pages = mutableListOf<String>()
        forwards.open("b1", "gitea_d1", "https://192.168.10.20:31443/explore", false, pages::add)
        runCurrent()
        assertEquals(listOf("https://gitea-d1.localhost:31443/explore"), pages)
        assertEquals(0, asked)
        assertTrue(forwards.rows.value.getValue("b1/gitea_d1").isForwarded)
        forwards.stopAll()
    }

    @Test
    fun aSecondOpenReusesTheForwardAndReadsANewToken() = runTest {
        var asked = 0
        val forwards = PortForwards({ _, _ ->
            asked += 1
            ChannelResult.Ok(JsonObject(mapOf("token" to JsonPrimitive("t$asked"))))
        }, streams, backgroundScope, table)
        val pages = mutableListOf<String>()
        forwards.open("b1", "c1", "http://192.168.10.20:31002/", true, pages::add)
        runCurrent()
        forwards.open("b1", "c1", "http://192.168.10.20:31002/", true, pages::add)
        runCurrent()
        assertEquals(listOf("http://c1.localhost:31002/?tkn=t1", "http://c1.localhost:31002/?tkn=t2"), pages)
        forwards.stopAll()
    }

    @Test
    fun aSlugKeepsLettersDigitsAndHyphensOnly() {
        assertEquals("vscode-argon-iffi", PortForwards.slugOf("vscode:argon/iffi"))
        assertEquals("Web-1", PortForwards.slugOf("Web 1"))
    }

    @Test
    fun theConfigureDialogIsRefusedWhileTheEntryIsForwarded() = runTest {
        val forwards = PortForwards(noMaterial, streams, backgroundScope, table)
        forwards.connect("b1", "p1", 30080)
        runCurrent()
        val answer = forwards.configure("b1", "p1", LocalPortChoice(isFixed = true, port = 30001))
        assertEquals("disconnect_first", (answer as ChannelResult.Refused).code)
        forwards.disconnect("b1", "p1")
        runCurrent()
        assertEquals(
            ChannelResult.Ok(Unit),
            forwards.configure("b1", "p1", LocalPortChoice(isFixed = true, port = 30001)),
        )
        assertEquals(LocalPortChoice(isFixed = true, port = 30001), forwards.localPortOf("b1", "p1"))
    }

    @Test
    fun twoEntriesOnOnePublishedPortForwardOnTwoLocalPorts() = runTest {
        val forwards = PortForwards(noMaterial, streams, backgroundScope, table)
        forwards.connect("b1", "p1", 30080)
        forwards.connect("b2", "p1", 30080)
        runCurrent()
        val first = forwards.rows.value.getValue("b1/p1").localPort
        val second = forwards.rows.value.getValue("b2/p1").localPort
        assertEquals(30080, first)
        assertTrue(second >= 20000)
        assertTrue(first != second)
        forwards.stopAll()
    }

    @Test
    fun openWithNoTokenWritesItsCode() = runTest {
        val forwards = PortForwards(noMaterial, streams, backgroundScope, table)
        val pages = mutableListOf<String>()
        forwards.open("b1", "w1", "http://192.168.10.20:31003/", true, pages::add)
        runCurrent()
        assertEquals("web_token_missing", forwards.rows.value["b1/w1"]?.error?.code)
        assertTrue(pages.isEmpty())
        forwards.stopAll()
    }

    @Test
    fun aRefusedTokenWritesTheCode() = runTest {
        val forwards = PortForwards(
            { _, _ -> ChannelResult.refused("permission_denied", "kind" to "web") },
            streams,
            backgroundScope,
            table,
        )
        val pages = mutableListOf<String>()
        forwards.open("b1", "c1", "http://h:31004/", true, pages::add)
        runCurrent()
        assertEquals("permission_denied", forwards.rows.value["b1/c1"]?.error?.code)
        assertTrue(pages.isEmpty())
        forwards.stopAll()
    }

    @Test
    fun aTokenJoinsTheAddressOwnQuery() {
        assertEquals("http://h:3001/?tkn=t", PortForwards.tokenUrlOf("http://h:3001/", "t"))
        assertEquals("http://h:3001/x?a=1&tkn=t", PortForwards.tokenUrlOf("http://h:3001/x?a=1", "t"))
    }

    @Test
    fun thePanelForwardsFrom20000UpAndOpensUnderTheHubsOwnName() = runTest {
        val forwards = PortForwards(noMaterial, streams, backgroundScope, table)
        val pages = mutableListOf<String>()
        forwards.openPanel("b1", "hub_7f.2", pages::add)
        assertEquals(PortForwardJob.OPENING, forwards.rows.value[PortForwards.panelKeyOf("b1")]?.job)
        runCurrent()
        val row = forwards.rows.value.getValue(PortForwards.panelKeyOf("b1"))
        assertTrue(row.localPort >= 20000)
        assertEquals(listOf("http://panel-hub-7f-2.localhost:${row.localPort}/"), pages)
        assertEquals("ok", exchange(row.localPort, "ok"))
        assertEquals(JsonPrimitive(true), opened.single().second["is_panel"])
        assertNull(opened.single().second["id"])
        forwards.stopAll()
    }

    @Test
    fun thePanelForwardStopsWhenTheHubNoLongerAllowsIt() = runTest {
        val forwards = PortForwards(noMaterial, streams, backgroundScope, table)
        forwards.openPanel("b1", "h1") {}
        runCurrent()
        forwards.take(listOf(hub("b1", HubConnection.CONNECTED).copy(isPanelAllowed = true)))
        assertTrue(forwards.rows.value.getValue(PortForwards.panelKeyOf("b1")).isForwarded)
        forwards.take(listOf(hub("b1", HubConnection.CONNECTED)))
        assertNull(forwards.rows.value[PortForwards.panelKeyOf("b1")])
    }

    @Test
    fun aHeldForwardShowsNoRowAndEndsOnRelease() = runTest {
        val forwards = PortForwards(noMaterial, streams, backgroundScope, table)
        val bound = (forwards.hold("b1", "r1", 31118) as ChannelResult.Ok).value
        assertEquals(31118, bound)
        assertNull(forwards.rows.value["b1/r1"])
        assertEquals("rd", exchange(bound, "rd"))
        forwards.release("b1", "r1")
        assertTrue(isFree(bound))
    }

    @Test
    fun aForwardStopsWhenItsEntryLeavesTheState() = runTest {
        val forwards = PortForwards(noMaterial, streams, backgroundScope, table)
        forwards.connect("b1", "p1", 30080)
        runCurrent()
        forwards.take(listOf(hub("b1", HubConnection.CONNECTING)))
        assertTrue(forwards.rows.value.getValue("b1/p1").isForwarded)
        forwards.take(listOf(hub("b1", HubConnection.CONNECTED, "p1")))
        assertTrue(forwards.rows.value.getValue("b1/p1").isForwarded)
        forwards.take(listOf(hub("b1", HubConnection.CONNECTED)))
        assertNull(forwards.rows.value["b1/p1"])
    }

    @Test
    fun leavingAHubEndsItsForwards() = runTest {
        val forwards = PortForwards(noMaterial, streams, backgroundScope, table)
        forwards.connect("b1", "p1", 30080)
        forwards.connect("b2", "p1", 30080)
        runCurrent()
        val port = forwards.rows.value.getValue("b1/p1").localPort
        forwards.forget("b1")
        assertNull(forwards.rows.value["b1/p1"])
        assertTrue(isFree(port))
        forwards.stopAll()
        assertTrue(forwards.rows.value.isEmpty())
    }

    private fun exchange(port: Int, text: String): String = Socket("127.0.0.1", port).use { client ->
        client.soTimeout = 5000
        client.getOutputStream().write(text.toByteArray())
        val echoed = ByteArray(text.length)
        var read = 0
        while (read < echoed.size) {
            val count = client.getInputStream().read(echoed, read, echoed.size - read)
            if (count < 0) break
            read += count
        }
        String(echoed, 0, read)
    }

    private fun hub(id: String, connection: HubConnection, vararg entries: String) = HubView(
        binding = HubBinding(id = id, gatewayUrl = "https://10.0.0.1:8443", fingerprint = "f", token = "t"),
        connection = connection,
        services = entries.map { ChannelServiceEntry(id = it, type = "port", title = it) },
    )

    private fun isFree(port: Int): Boolean = try {
        ServerSocket(port, 50, InetAddress.getByName("127.0.0.1")).close()
        true
    } catch (_: java.io.IOException) {
        false
    }

    private class FailingRelay(name: String, open: () -> ChannelResult<ChannelStream>) :
        PortForwardRelay(name, open, 0) {
        override fun start(): Int = throw java.io.IOException("address in use")
    }
}
