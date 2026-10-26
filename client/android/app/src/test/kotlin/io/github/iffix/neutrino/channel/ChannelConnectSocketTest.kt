package io.github.iffix.neutrino.channel

import io.github.iffix.neutrino.ConnectRefusedException
import io.github.iffix.neutrino.transport.FakeTransport
import io.github.iffix.neutrino.transport.TransportStream
import java.io.IOException
import java.net.InetSocketAddress
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class ChannelConnectSocketTest {
    private val transport = FakeTransport().also { it.start("/data", "ee".repeat(32)) }

    private fun socket() = ChannelConnectSocket {
        TransportStream.open(
            transport,
            transport.secret,
            "b1",
            buildJsonObject {
                put("kind", "connect")
                put("id", "e1")
            },
        )
    }

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
        transport.serve = { _, end -> FakeTransport.accept(end) }
        val socket = socket()
        assertFalse(socket.isConnected)
        socket.connect(InetSocketAddress.createUnresolved("192.0.2.5", 445), 1000)
        assertTrue(socket.isConnected)
        val open = transport.opens.single()["open"]!!
        assertEquals("connect", (open as kotlinx.serialization.json.JsonObject)["kind"]?.jsonPrimitive?.content)
        assertEquals("e1", open["id"]?.jsonPrimitive?.content)
    }

    @Test
    fun whatIsWrittenGoesUpRawAndWhatTheHubSendsIsRead() {
        transport.serve = { _, end ->
            FakeTransport.accept(end)
            val got = ByteArray(5)
            var read = 0
            while (read < 5) read += end.input.read(got, read, 5 - read)
            end.output.write(got)
        }
        val socket = socket().apply { open() }
        socket.getOutputStream().write("hello".toByteArray())
        assertArrayEquals("hello".toByteArray(), readFully(socket, 5))
    }

    @Test
    fun aStreamTheHubRefusesIsAConnectRefusal() {
        transport.serve =
            { _, end -> FakeTransport.refuse(end, "agent_offline", buildJsonObject { put("device", "lab") }) }
        val socket = socket()
        try {
            socket.open()
            fail("the open went through")
        } catch (error: ConnectRefusedException) {
            assertEquals("agent_offline", error.code)
        }
        assertEquals("agent_offline", socket.refusal?.code)
        assertFalse(socket.isConnected)
    }

    @Test
    fun theEndOfTheHubsBytesIsTheEndOfTheSocket() {
        transport.serve = { _, end ->
            FakeTransport.accept(end)
            end.output.write("bye".toByteArray())
            end.close()
        }
        val socket = socket().apply { open() }
        assertArrayEquals("bye".toByteArray(), readFully(socket, 3))
        assertEquals(-1, socket.getInputStream().read())
    }

    @Test
    fun aClosedSocketWritesNothing() {
        transport.serve = { _, end -> FakeTransport.accept(end) }
        val socket = socket().apply { open() }
        socket.close()
        assertTrue(socket.isClosed)
        try {
            socket.getOutputStream().write(1)
            fail("a closed socket wrote")
        } catch (_: IOException) {
            return
        }
    }
}
