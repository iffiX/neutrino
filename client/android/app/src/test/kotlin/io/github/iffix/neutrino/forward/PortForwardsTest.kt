package io.github.iffix.neutrino.forward

import io.github.iffix.neutrino.FakeSharedPreferences
import io.github.iffix.neutrino.binding.HubBinding
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.ChannelServiceEntry
import io.github.iffix.neutrino.channel.HubConnection
import io.github.iffix.neutrino.channel.HubView
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class PortForwardsTest {
    private val echo = EchoServer()
    private val table = LocalPortTable(FakeSharedPreferences())
    private val noMaterial: suspend (String, String) -> ChannelResult<JsonObject> = { _, _ ->
        ChannelResult.Ok(JsonObject(emptyMap()))
    }

    @After
    fun closeEcho() = echo.close()

    @Test
    fun connectIsAJobUntilTheLoopbackListens() = runTest {
        val forwards = PortForwards(noMaterial, backgroundScope, table)
        forwards.connect("b1", "p1", "127.0.0.1", echo.port)
        assertEquals(PortForwardJob.FORWARDING, forwards.rows.value["b1/p1"]?.job)
        runCurrent()
        val row = forwards.rows.value.getValue("b1/p1")
        assertNull(row.job)
        assertTrue(row.isForwarded)
        Socket("127.0.0.1", row.localPort).use { assertTrue(it.isConnected) }
        forwards.stopAll()
    }

    @Test
    fun aSecondPressWhileTheJobRunsIsDropped() = runTest {
        var made = 0
        val forwards = PortForwards(noMaterial, backgroundScope, table) { host, port, local ->
            made += 1
            PortForwardRelay(host, port, local)
        }
        forwards.connect("b1", "p1", "127.0.0.1", echo.port)
        forwards.connect("b1", "p1", "127.0.0.1", echo.port)
        runCurrent()
        assertEquals(1, made)
        forwards.stopAll()
    }

    @Test
    fun disconnectIsAJobThenTheRowGoes() = runTest {
        val forwards = PortForwards(noMaterial, backgroundScope, table)
        forwards.connect("b1", "p1", "127.0.0.1", echo.port)
        runCurrent()
        forwards.disconnect("b1", "p1")
        assertEquals(PortForwardJob.DISCONNECTING, forwards.rows.value["b1/p1"]?.job)
        runCurrent()
        assertNull(forwards.rows.value["b1/p1"])
    }

    @Test
    fun aFailedBindWritesForwardFailedUntilARefresh() = runTest {
        val forwards = PortForwards(noMaterial, backgroundScope, table) { host, port, _ ->
            FailingRelay(host, port)
        }
        forwards.connect("b1", "p1", "127.0.0.1", echo.port)
        runCurrent()
        assertEquals("forward_failed", forwards.rows.value["b1/p1"]?.error?.code)
        forwards.clearErrors()
        assertNull(forwards.rows.value["b1/p1"])
    }

    @Test
    fun openLocallyForwardsTakesTheTokenAndOpensTheEntrysOwnLocalhostName() = runTest {
        val answer = CompletableDeferred<ChannelResult<JsonObject>>()
        val forwards = PortForwards({ _, _ -> answer.await() }, backgroundScope, table)
        val opened = mutableListOf<String>()
        forwards.openLocal("b1", "vscode-argon_iffi.1", "http://127.0.0.1:${echo.port}/", opened::add)
        runCurrent()
        assertEquals(PortForwardJob.OPENING, forwards.rows.value["b1/vscode-argon_iffi.1"]?.job)
        answer.complete(ChannelResult.Ok(JsonObject(mapOf("token" to JsonPrimitive("a b")))))
        runCurrent()
        val row = forwards.rows.value.getValue("b1/vscode-argon_iffi.1")
        assertEquals(listOf("http://vscode-argon-iffi-1.localhost:${row.localPort}/?tkn=a+b"), opened)
        assertNull(row.job)
        Socket("127.0.0.1", row.localPort).use { client ->
            client.soTimeout = 5000
            client.getOutputStream().write("GET / HTTP/1.1\r\n\r\n".toByteArray())
            val echoed = ByteArray(16)
            var read = 0
            while (read < 16) read += client.getInputStream().read(echoed, read, 16 - read)
            assertEquals("GET / HTTP/1.1\r\n", String(echoed))
        }
        forwards.stopAll()
    }

    @Test
    fun aSlugKeepsLettersDigitsAndHyphensOnly() {
        assertEquals("vscode-argon-iffi", PortForwards.slugOf("vscode:argon/iffi"))
        assertEquals("Web-1", PortForwards.slugOf("Web 1"))
    }

    @Test
    fun theConfigureDialogIsRefusedWhileTheEntryIsForwarded() = runTest {
        val forwards = PortForwards(noMaterial, backgroundScope, table)
        forwards.connect("b1", "p1", "127.0.0.1", echo.port)
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
        val forwards = PortForwards(noMaterial, backgroundScope, table)
        forwards.connect("b1", "p1", "127.0.0.1", echo.port)
        forwards.connect("b2", "p1", "127.0.0.1", echo.port)
        runCurrent()
        val first = forwards.rows.value.getValue("b1/p1").localPort
        val second = forwards.rows.value.getValue("b2/p1").localPort
        assertTrue(first >= 20000 && second >= 20000)
        assertTrue(first != second)
        forwards.stopAll()
    }

    @Test
    fun openLocallyWithNoTokenWritesItsCode() = runTest {
        val forwards = PortForwards(noMaterial, backgroundScope, table)
        val opened = mutableListOf<String>()
        forwards.openLocal("b1", "w1", "http://127.0.0.1:${echo.port}/", opened::add)
        runCurrent()
        assertEquals("web_token_missing", forwards.rows.value["b1/w1"]?.error?.code)
        assertTrue(opened.isEmpty())
        forwards.stopAll()
    }

    @Test
    fun openWithATokenIsAJobThatOpensTheEntrysOwnAddressAndForwardsNothing() = runTest {
        val answer = CompletableDeferred<ChannelResult<JsonObject>>()
        var made = 0
        val forwards = PortForwards({ _, _ -> answer.await() }, backgroundScope, table) { host, port, local ->
            made += 1
            PortForwardRelay(host, port, local)
        }
        val opened = mutableListOf<String>()
        forwards.openWithToken("b1", "cloudcli_d1_ann", "http://192.168.1.5:3001/", opened::add)
        runCurrent()
        assertEquals(PortForwardJob.OPENING, forwards.rows.value["b1/cloudcli_d1_ann"]?.job)
        forwards.openWithToken("b1", "cloudcli_d1_ann", "http://192.168.1.5:3001/", opened::add)
        answer.complete(ChannelResult.Ok(JsonObject(mapOf("token" to JsonPrimitive("a-b_c")))))
        runCurrent()
        assertEquals(listOf("http://192.168.1.5:3001/?tkn=a-b_c"), opened)
        assertNull(forwards.rows.value["b1/cloudcli_d1_ann"])
        assertEquals(0, made)
    }

    @Test
    fun openWithATokenThatIsRefusedOrMissingWritesTheCode() = runTest {
        val refused = PortForwards(
            { _, _ -> ChannelResult.refused("permission_denied", "kind" to "web") },
            backgroundScope,
            table,
        )
        val opened = mutableListOf<String>()
        refused.openWithToken("b1", "c1", "http://h:3001/", opened::add)
        runCurrent()
        assertEquals("permission_denied", refused.rows.value["b1/c1"]?.error?.code)
        val missing = PortForwards(noMaterial, backgroundScope, table)
        missing.openWithToken("b1", "c1", "http://h:3001/", opened::add)
        runCurrent()
        assertEquals("web_token_missing", missing.rows.value["b1/c1"]?.error?.code)
        assertTrue(opened.isEmpty())
    }

    @Test
    fun aTokenJoinsTheAddressOwnQuery() {
        assertEquals("http://h:3001/?tkn=t", PortForwards.tokenUrlOf("http://h:3001/", "t"))
        assertEquals("http://h:3001/x?a=1&tkn=t", PortForwards.tokenUrlOf("http://h:3001/x?a=1", "t"))
    }

    @Test
    fun aForwardStopsWhenItsEntryLeavesTheState() = runTest {
        val forwards = PortForwards(noMaterial, backgroundScope, table)
        forwards.connect("b1", "p1", "127.0.0.1", echo.port)
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
        val forwards = PortForwards(noMaterial, backgroundScope, table)
        forwards.connect("b1", "p1", "127.0.0.1", echo.port)
        forwards.connect("b2", "p1", "127.0.0.1", echo.port)
        runCurrent()
        val port = forwards.rows.value.getValue("b1/p1").localPort
        forwards.forget("b1")
        assertNull(forwards.rows.value["b1/p1"])
        assertTrue(isFree(port))
        forwards.stopAll()
        assertTrue(forwards.rows.value.isEmpty())
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

    private class FailingRelay(host: String, port: Int) : PortForwardRelay(host, port, 0) {
        override fun start(): Int = throw java.io.IOException("address in use")
    }
}
