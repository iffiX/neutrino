package io.github.iffix.neutrino.forward

import io.github.iffix.neutrino.channel.ChannelFrames
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.FakeConnectHub
import java.io.IOException
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class PortForwardRelayTest {
    private val opened = mutableListOf<AutoCloseable>()

    @After
    fun closeAll() = opened.forEach { it.close() }

    @Test
    fun everyAcceptedConnectionIsOneConnectStreamNamingTheEntry() {
        val hub = FakeConnectHub()
        val relay = relay(hub, preferred = 0)
        val bound = relay.start()
        assertTrue(relay.isActive)
        repeat(2) {
            Socket("127.0.0.1", bound).use { client ->
                client.soTimeout = 5000
                client.getOutputStream().write("hello".toByteArray())
                assertArrayEquals("hello".toByteArray(), readFully(client, 5))
            }
        }
        waitFor { hub.opens.size == 2 }
        assertEquals(listOf("e1", "e1"), hub.opens.map { it["id"]?.jsonPrimitive?.content })
        assertEquals(listOf("connect", "connect"), hub.opens.map { it["kind"]?.jsonPrimitive?.content })
    }

    @Test
    fun theLoopbackTakesThePreferredNumberWhenFree() {
        val free = ServerSocket(0).use { it.localPort }
        assertEquals(free, relay(FakeConnectHub(), preferred = free).start())
    }

    @Test(expected = IOException::class)
    fun aTakenNumberDoesNotStart() {
        val taken = ServerSocket(0, 50, InetAddress.getByName("127.0.0.1")).also { opened += it }
        relay(FakeConnectHub(), preferred = taken.localPort).start()
    }

    @Test
    fun theHubsEndOfFileWritesWhatCameAndClosesTheConnection() {
        val hub = FakeConnectHub(isGranting = false)
        val client = Socket("127.0.0.1", relay(hub, preferred = 0).start()).also { opened += it }
        client.soTimeout = 5000
        waitFor { hub.opens.isNotEmpty() }
        val stream = hub.opens.single()["stream"]!!.jsonPrimitive.content.toInt()
        hub.send(stream, "bye".toByteArray())
        hub.end(stream)
        assertArrayEquals("bye".toByteArray(), readFully(client, 3))
        assertEquals(-1, readOrEnd(client))
    }

    @Test
    fun theConnectionsEndOfFileClosesTheStream() {
        val hub = FakeConnectHub()
        val client = Socket("127.0.0.1", relay(hub, preferred = 0).start())
        waitFor { hub.opens.isNotEmpty() }
        client.close()
        waitFor { hub.closed.isNotEmpty() }
        assertEquals(hub.opens.single()["stream"]!!.jsonPrimitive.content.toInt(), hub.closed.single())
    }

    @Test
    fun aRefusedStreamClosesTheAcceptedConnection() {
        val hub = FakeConnectHub(refusal = ChannelResult.refused("permission_denied", "kind" to "port"))
        val client = Socket("127.0.0.1", relay(hub, preferred = 0).start()).also { opened += it }
        client.soTimeout = 5000
        assertEquals(-1, readOrEnd(client))
    }

    @Test
    fun aHubThatIsNotConnectedClosesTheAcceptedConnection() {
        val relay = PortForwardRelay("b1/e1", { ChannelResult.refused("hub_unreachable") }, 0).also { opened += it }
        val client = Socket("127.0.0.1", relay.start()).also { opened += it }
        client.soTimeout = 5000
        assertEquals(-1, readOrEnd(client))
    }

    @Test
    fun closingStopsTheListenerAndEveryConnection() {
        val hub = FakeConnectHub()
        val relay = relay(hub, preferred = 0)
        val bound = relay.start()
        val client = Socket("127.0.0.1", bound).also { opened += it }
        client.soTimeout = 5000
        client.getOutputStream().write(1)
        assertEquals(1, client.getInputStream().read())
        relay.close()
        assertFalse(relay.isActive)
        assertEquals(-1, readOrEnd(client))
        waitFor { hub.closed.isNotEmpty() }
        try {
            Socket().use { it.connect(InetSocketAddress("127.0.0.1", bound), 1000) }
            fail("the loopback still listens")
        } catch (_: IOException) {
            // Refused, as a closed listener is.
        }
    }

    private fun relay(hub: FakeConnectHub, preferred: Int): PortForwardRelay =
        PortForwardRelay("b1/e1", { hub.open(ChannelFrames.args("id" to "e1")) }, preferred).also { opened += it }

    private fun readFully(client: Socket, size: Int): ByteArray {
        val data = ByteArray(size)
        var read = 0
        while (read < size) {
            val count = client.getInputStream().read(data, read, size - read)
            if (count < 0) break
            read += count
        }
        return data.copyOf(read)
    }

    private fun readOrEnd(client: Socket): Int = try {
        client.getInputStream().read()
    } catch (_: IOException) {
        -1
    }

    private fun waitFor(condition: () -> Boolean) {
        val deadline = System.currentTimeMillis() + 5000
        while (!condition()) {
            if (System.currentTimeMillis() > deadline) fail("the condition did not hold in 5 s")
            Thread.sleep(10)
        }
    }
}
