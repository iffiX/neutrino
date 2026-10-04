package io.github.iffix.neutrino.channel

import io.github.iffix.neutrino.CLIENT_STREAM_CREDIT_BYTES
import io.github.iffix.neutrino.CLIENT_WS_CHUNK_BYTES
import io.github.iffix.neutrino.ConnectRefusedException
import java.net.InetSocketAddress
import kotlin.concurrent.thread
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class ChannelConnectSocketTest {
    private fun socketOn(hub: FakeConnectHub) = ChannelConnectSocket { hub.open(ChannelFrames.args("id" to "e1")) }

    private fun readFully(socket: ChannelConnectSocket, size: Int): ByteArray {
        val data = ByteArray(size)
        var read = 0
        while (read < size) {
            val count = socket.getInputStream().read(data, read, size - read)
            if (count < 0) break
            read += count
        }
        return data.copyOf(read)
    }

    @Test
    fun connectingOpensOneConnectStreamNamingTheEntryAndDialsNothing() {
        val hub = FakeConnectHub()
        val socket = socketOn(hub)
        assertFalse(socket.isConnected)
        socket.connect(InetSocketAddress.createUnresolved("192.0.2.5", 445), 1000)
        assertTrue(socket.isConnected)
        val open = hub.opens.single()
        assertEquals("connect", open["kind"]?.jsonPrimitive?.content)
        assertEquals("e1", open["id"]?.jsonPrimitive?.content)
        assertEquals(CLIENT_STREAM_CREDIT_BYTES, hub.credits.single().second)
    }

    @Test
    fun whatIsWrittenGoesUpAndWhatTheHubSendsIsRead() {
        val hub = FakeConnectHub()
        val socket = socketOn(hub).apply { open() }
        socket.getOutputStream().write("hello".toByteArray())
        assertArrayEquals("hello".toByteArray(), hub.frames.single())
        assertArrayEquals("hello".toByteArray(), readFully(socket, 5))
    }

    @Test
    fun aWriteIsSentInFramesOfAtMostOneChunk() {
        val hub = FakeConnectHub()
        val socket = socketOn(hub).apply { open() }
        socket.getOutputStream().write(ByteArray(CLIENT_WS_CHUNK_BYTES * 2 + 10))
        assertEquals(listOf(CLIENT_WS_CHUNK_BYTES, CLIENT_WS_CHUNK_BYTES, 10), hub.frames.map { it.size })
    }

    @Test
    fun aWriteWaitsForTheHubsCredit() {
        val hub = FakeConnectHub(isGranting = false)
        val socket = socketOn(hub).apply { open() }
        val stream = hub.opens.single()["stream"]!!.jsonPrimitive.content.toInt()
        hub.grant(stream, 4)
        val writer = thread { socket.getOutputStream().write("abcdefgh".toByteArray()) }
        Thread.sleep(200)
        assertEquals(listOf("abcd"), hub.frames.map { String(it) })
        assertTrue(writer.isAlive)
        hub.grant(stream, 4)
        writer.join(5000)
        assertFalse(writer.isAlive)
        assertEquals(listOf("abcd", "efgh"), hub.frames.map { String(it) })
    }

    @Test
    fun consumingHalfTheWindowGrantsMore() {
        val hub = FakeConnectHub(isGranting = false)
        val socket = socketOn(hub).apply { open() }
        val stream = hub.opens.single()["stream"]!!.jsonPrimitive.content.toInt()
        val half = CLIENT_STREAM_CREDIT_BYTES / 2
        hub.send(stream, ByteArray(half - 1))
        hub.send(stream, ByteArray(2))
        assertEquals(1, hub.credits.size)
        assertEquals(half - 1, readFully(socket, half - 1).size)
        assertEquals(1, hub.credits.size)
        assertEquals(2, readFully(socket, 2).size)
        assertEquals(stream to half + 1, hub.credits.last())
    }

    @Test
    fun theHubsEndOfFileIsReadAsTheEnd() {
        val hub = FakeConnectHub()
        val socket = socketOn(hub).apply { open() }
        val stream = hub.opens.single()["stream"]!!.jsonPrimitive.content.toInt()
        hub.send(stream, "tail".toByteArray())
        hub.end(stream)
        assertArrayEquals("tail".toByteArray(), readFully(socket, 4))
        assertEquals(-1, socket.getInputStream().read())
    }

    @Test
    fun aRefusalEndsTheFirstReadWithItsCode() {
        val hub = FakeConnectHub(refusal = ChannelResult.refused("permission_denied", "kind" to "file"))
        val socket = socketOn(hub).apply { open() }
        try {
            socket.getInputStream().read()
            fail("a refused stream was read")
        } catch (error: ConnectRefusedException) {
            assertEquals("permission_denied", error.code)
            assertEquals("file", error.params["kind"]?.jsonPrimitive?.content)
        }
    }

    @Test
    fun aStreamThatCannotOpenRefusesTheConnect() {
        val socket = ChannelConnectSocket { ChannelResult.refused("hub_unreachable") }
        try {
            socket.connect(InetSocketAddress.createUnresolved("192.0.2.5", 445))
            fail("a socket connected with no stream")
        } catch (error: ConnectRefusedException) {
            assertEquals("hub_unreachable", error.code)
        }
    }

    @Test
    fun closingEndsTheStreamOnceAndEndsReads() {
        val hub = FakeConnectHub()
        val socket = socketOn(hub).apply { open() }
        socket.close()
        socket.close()
        assertTrue(socket.isClosed)
        assertEquals(1, hub.closed.size)
        assertEquals(-1, socket.getInputStream().read())
    }

    @Test
    fun shuttingOutputClosesTheWholeSocket() {
        val hub = FakeConnectHub()
        val socket = socketOn(hub).apply { open() }
        socket.shutdownOutput()
        assertTrue(socket.isClosed)
        assertEquals(1, hub.closed.size)
    }

    @Test
    fun theHubSocketEndingEndsAReadWithUnreachable() {
        val hub = FakeConnectHub()
        val socket = socketOn(hub).apply { open() }
        hub.registry.endAll()
        try {
            socket.getInputStream().read()
            fail("a read outlived the hub's socket")
        } catch (error: ConnectRefusedException) {
            assertEquals("hub_unreachable", error.code)
        }
    }
}
