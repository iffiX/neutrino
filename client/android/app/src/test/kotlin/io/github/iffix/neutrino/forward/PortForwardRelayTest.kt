package io.github.iffix.neutrino.forward

import java.io.IOException
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class PortForwardRelayTest {
    private val echo = EchoServer()
    private val opened = mutableListOf<AutoCloseable>()

    @After
    fun closeAll() {
        opened.forEach { it.close() }
        echo.close()
    }

    @Test
    fun aConnectionToTheLoopbackReachesThePublishedPort() {
        val relay = relay(preferred = 0)
        val bound = relay.start()
        assertTrue(relay.isActive)
        Socket("127.0.0.1", bound).use { client ->
            client.soTimeout = 5000
            client.getOutputStream().write("hello".toByteArray())
            val answer = ByteArray(5)
            var read = 0
            while (read < 5) read += client.getInputStream().read(answer, read, 5 - read)
            assertArrayEquals("hello".toByteArray(), answer)
        }
    }

    @Test
    fun theLoopbackTakesThePreferredNumberWhenFree() {
        val free = ServerSocket(0).use { it.localPort }
        assertEquals(free, relay(preferred = free).start())
    }

    @Test
    fun aTakenNumberGivesAnyFreeOne() {
        val taken = ServerSocket(0, 50, InetAddress.getByName("127.0.0.1")).also { opened += it }
        val bound = relay(preferred = taken.localPort).start()
        assertNotEquals(taken.localPort, bound)
        assertNotEquals(0, bound)
    }

    @Test
    fun closingStopsTheListenerAndEveryConnection() {
        val relay = relay(preferred = 0)
        val bound = relay.start()
        val client = Socket("127.0.0.1", bound).also { opened += it }
        client.soTimeout = 5000
        client.getOutputStream().write(1)
        assertEquals(1, client.getInputStream().read())
        relay.close()
        assertFalse(relay.isActive)
        assertEquals(-1, readOrEnd(client))
        try {
            Socket().use { it.connect(InetSocketAddress("127.0.0.1", bound), 1000) }
            fail("the loopback still listens")
        } catch (_: IOException) {
            // Refused, as a closed listener is.
        }
    }

    @Test
    fun anUnreachablePublishedPortClosesTheAcceptedConnection() {
        val closed = ServerSocket(0).use { it.localPort }
        val relay = PortForwardRelay("127.0.0.1", closed, 0).also { opened += it }
        val client = Socket("127.0.0.1", relay.start()).also { opened += it }
        client.soTimeout = 5000
        assertEquals(-1, readOrEnd(client))
    }

    private fun relay(preferred: Int): PortForwardRelay =
        PortForwardRelay("127.0.0.1", echo.port, preferred).also { opened += it }

    private fun readOrEnd(client: Socket): Int = try {
        client.getInputStream().read()
    } catch (_: IOException) {
        -1
    }
}
