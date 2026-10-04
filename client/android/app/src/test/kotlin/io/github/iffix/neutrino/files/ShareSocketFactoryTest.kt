package io.github.iffix.neutrino.files

import io.github.iffix.neutrino.ConnectRefusedException
import io.github.iffix.neutrino.channel.ChannelConnectSocket
import io.github.iffix.neutrino.channel.ChannelFrames
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.FakeConnectHub
import java.net.InetSocketAddress
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class ShareSocketFactoryTest {
    private val hub = FakeConnectHub()
    private val factory = ShareSocketFactory { hub.open(ChannelFrames.args("id" to "f1")) }

    @Test
    fun aSocketForTheSharesHostIsAConnectStreamNamingTheFileEntry() {
        factory.createSocket("192.0.2.5", 445).use { socket ->
            assertTrue(socket is ChannelConnectSocket)
            assertTrue(socket.isConnected)
            socket.getOutputStream().write(byteArrayOf(0, 0, 0, 1, 7))
            val echoed = ByteArray(5)
            var read = 0
            while (read < 5) read += socket.getInputStream().read(echoed, read, 5 - read)
            assertArrayEquals(byteArrayOf(0, 0, 0, 1, 7), echoed)
        }
        val open = hub.opens.single()
        assertEquals("connect", open["kind"]?.jsonPrimitive?.content)
        assertEquals("f1", open["id"]?.jsonPrimitive?.content)
        assertEquals(1, hub.closed.size)
    }

    @Test
    fun anUnconnectedSocketOpensItsStreamOnConnect() {
        val socket = factory.createSocket()
        assertFalse(socket.isConnected)
        assertTrue(hub.opens.isEmpty())
        socket.connect(InetSocketAddress.createUnresolved("192.0.2.5", 445), 5000)
        assertEquals(1, hub.opens.size)
        socket.close()
    }

    @Test
    fun theSoTimeoutTheLibrarySetsIsKept() {
        val socket = factory.createSocket()
        socket.soTimeout = 60_000
        assertEquals(60_000, socket.soTimeout)
    }

    @Test
    fun aHubThatIsNotConnectedRefusesTheSocket() {
        val refused = ShareSocketFactory { ChannelResult.refused("hub_unreachable") }
        try {
            refused.createSocket("192.0.2.5", 445)
            fail("a socket opened with no hub")
        } catch (error: ConnectRefusedException) {
            assertEquals("hub_unreachable", error.code)
        }
    }
}
