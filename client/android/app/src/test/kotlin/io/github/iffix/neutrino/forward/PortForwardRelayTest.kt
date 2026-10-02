package io.github.iffix.neutrino.forward

import java.io.IOException
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import kotlin.concurrent.thread
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
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

    @Test(expected = IOException::class)
    fun aTakenNumberDoesNotStart() {
        val taken = ServerSocket(0, 50, InetAddress.getByName("127.0.0.1")).also { opened += it }
        relay(preferred = taken.localPort).start()
    }

    @Test
    fun aWebForwardSendsTheTokenAsTheCookieAndDropsTheServersTokenCookie() {
        val server = ServerSocket(0, 50, InetAddress.getByName("127.0.0.1")).also { opened += it }
        var received = ""
        val serving = thread(isDaemon = true) {
            server.accept().use { socket ->
                received = WebTokenHeaders.read(socket.getInputStream())?.first.orEmpty()
                socket.getOutputStream().write(
                    (
                        "HTTP/1.1 200 OK\r\nSet-Cookie: vscode-tkn=x; Path=/\r\nSet-Cookie: theme=dark\r\n" +
                            "Content-Length: 2\r\n\r\nok"
                        ).toByteArray(),
                )
            }
        }
        val relay = PortForwardRelay("127.0.0.1", server.localPort, 0, "t0k").also { opened += it }
        val answer = Socket("127.0.0.1", relay.start()).use { client ->
            client.soTimeout = 5000
            client.getOutputStream().write(
                "GET / HTTP/1.1\r\nHost: 127.0.0.1\r\nCookie: vscode-tkn=old\r\n\r\n".toByteArray(),
            )
            String(client.getInputStream().readBytes())
        }
        serving.join(5000)
        assertTrue(received, received.contains("Cookie: vscode-tkn=t0k\r\n"))
        assertTrue(received, received.contains("Connection: close\r\n"))
        assertFalse(received, received.contains("old"))
        assertEquals("HTTP/1.1 200 OK\r\nSet-Cookie: theme=dark\r\nContent-Length: 2\r\n\r\nok", answer)
    }

    @Test
    fun aWebForwardPassesAnUpgradeAndThenRelaysBytes() {
        val server = ServerSocket(0, 50, InetAddress.getByName("127.0.0.1")).also { opened += it }
        thread(isDaemon = true) {
            server.accept().use { socket ->
                WebTokenHeaders.read(socket.getInputStream())
                val upgrade = "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n"
                socket.getOutputStream().write(upgrade.toByteArray())
                val frame = ByteArray(4)
                var read = 0
                while (read < 4) read += socket.getInputStream().read(frame, read, 4 - read)
                socket.getOutputStream().write(frame)
            }
        }
        val relay = PortForwardRelay("127.0.0.1", server.localPort, 0, "t").also { opened += it }
        Socket("127.0.0.1", relay.start()).use { client ->
            client.soTimeout = 5000
            client.getOutputStream().write(
                "GET /ws HTTP/1.1\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n".toByteArray(),
            )
            val (head, rest) = requireNotNull(WebTokenHeaders.read(client.getInputStream()))
            assertTrue(head, head.startsWith("HTTP/1.1 101"))
            assertEquals(0, rest.size)
            client.getOutputStream().write("ping".toByteArray())
            val echoed = ByteArray(4)
            var read = 0
            while (read < 4) read += client.getInputStream().read(echoed, read, 4 - read)
            assertArrayEquals("ping".toByteArray(), echoed)
        }
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
