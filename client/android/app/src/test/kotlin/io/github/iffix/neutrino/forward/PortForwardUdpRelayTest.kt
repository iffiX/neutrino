package io.github.iffix.neutrino.forward

import io.github.iffix.neutrino.CLIENT_UDP_HELD_DATAGRAMS_MAX
import io.github.iffix.neutrino.CLIENT_UDP_SOURCES_MAX
import io.github.iffix.neutrino.ConnectRefusedException
import io.github.iffix.neutrino.channel.ChannelFrames
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.ChannelStream
import io.github.iffix.neutrino.channel.FakeConnectHub
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.SocketTimeoutException
import java.nio.ByteBuffer
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class PortForwardUdpRelayTest {
    private val opened = mutableListOf<AutoCloseable>()
    private val refusals = mutableListOf<Pair<String, Boolean>>()
    private var now = 0L

    @After
    fun closeAll() = opened.forEach { it.close() }

    @Test
    fun twoLocalProgramsThroughOneStreamEachGetTheirOwnReplies() {
        val hub = FakeConnectHub()
        val relay = relay { hub.open(ChannelFrames.args("id" to "u1")) }
        val port = relay.start()
        val first = program()
        val second = program()
        repeat(3) {
            send(first, port, "one-$it")
            send(second, port, "two-$it")
            assertEquals("one-$it", receive(first))
            assertEquals("two-$it", receive(second))
        }
        assertEquals(1, opensOf(hub).size)
        assertEquals("u1", opensOf(hub).single()["id"]?.jsonPrimitive?.content)
        val frame = framesOf(hub).first()
        assertEquals(first.localPort, ByteBuffer.wrap(frame, 0, 2).short.toInt() and 0xffff)
        assertArrayEquals("one-0".toByteArray(), frame.copyOfRange(2, frame.size))
    }

    @Test
    fun anEmptyDatagramIsATwoByteFrame() {
        val hub = FakeConnectHub()
        val port = relay { hub.open(ChannelFrames.args("id" to "u1")) }.start()
        val program = program()
        program.send(DatagramPacket(ByteArray(0), 0, InetSocketAddress("127.0.0.1", port)))
        waitFor { framesOf(hub).isNotEmpty() }
        assertEquals(2, framesOf(hub).single().size)
    }

    @Test
    fun atMostSixteenDatagramsAreHeldUntilTheFirstCredit() {
        val hub = FakeConnectHub(isGranting = false)
        val port = relay { hub.open(ChannelFrames.args("id" to "u1")) }.start()
        val program = program()
        repeat(CLIENT_UDP_HELD_DATAGRAMS_MAX + 4) { send(program, port, "d$it") }
        Thread.sleep(300)
        assertTrue(framesOf(hub).isEmpty())
        hub.grant(streamOf(hub), 1 shl 20)
        waitFor { framesOf(hub).size == CLIENT_UDP_HELD_DATAGRAMS_MAX }
        Thread.sleep(200)
        assertEquals(
            (0 until CLIENT_UDP_HELD_DATAGRAMS_MAX).map { "d$it" },
            framesOf(hub).map {
                String(
                    it,
                    2,
                    it.size - 2,
                )
            },
        )
    }

    @Test
    fun aDatagramTheCreditDoesNotCoverIsDroppedNotQueued() {
        val hub = FakeConnectHub(isGranting = false)
        val port = relay { hub.open(ChannelFrames.args("id" to "u1")) }.start()
        val stream = streamOf(hub)
        hub.grant(stream, 8)
        val program = program()
        send(program, port, "abcdefghij")
        send(program, port, "abc")
        waitFor { framesOf(hub).size == 1 }
        hub.grant(stream, 100)
        send(program, port, "xyz")
        waitFor { framesOf(hub).size == 2 }
        Thread.sleep(200)
        assertEquals(listOf("abc", "xyz"), framesOf(hub).map { String(it, 2, it.size - 2) })
    }

    @Test
    fun aFrameForASourceNoLongerRememberedIsDropped() {
        val hub = FakeConnectHub(isGranting = false)
        val port = relay { hub.open(ChannelFrames.args("id" to "u1")) }.start()
        val stream = streamOf(hub)
        hub.grant(stream, 1 shl 20)
        val programs = List(CLIENT_UDP_SOURCES_MAX + 1) { program() }
        for (program in programs) {
            send(program, port, "x")
            waitFor { framesOf(hub).any { sourceOf(it) == program.localPort } }
        }
        hub.send(stream, reply(programs.first().localPort, "lost"))
        hub.send(stream, reply(programs.last().localPort, "kept"))
        assertEquals("kept", receive(programs.last()))
        assertNull(receiveOrNull(programs.first(), QUIET_MILLIS))
    }

    @Test
    fun aStreamThatCannotOpenAtConnectRefusesTheForward() {
        val relay = relay { ChannelResult.refused("hub_unreachable") }
        try {
            relay.start()
            fail("a forward started with no stream")
        } catch (error: ConnectRefusedException) {
            assertEquals("hub_unreachable", error.code)
        }
        assertFalse(relay.isActive)
    }

    @Test
    fun aRefusalOfTheStreamOpenedAtConnectEndsTheForward() {
        val hub = FakeConnectHub(refusal = ChannelResult.refused("permission_denied", "kind" to "port"))
        val relay = relay { hub.open(ChannelFrames.args("id" to "u1")) }
        relay.start()
        waitFor { refusals.isNotEmpty() }
        assertEquals(listOf("permission_denied" to true), refusals)
        assertFalse(relay.isActive)
    }

    @Test
    fun aLaterRefusalKeepsListeningAndTriesAgainAtMostOnceASecond() {
        val hub = FakeConnectHub()
        var isRefused = false
        var tries = 0
        val relay = relay {
            tries += 1
            if (isRefused) {
                ChannelResult.refused("permission_denied", "kind" to "port")
            } else {
                hub.open(ChannelFrames.args("id" to "u1"))
            }
        }
        val port = relay.start()
        val program = program()
        send(program, port, "a")
        assertEquals("a", receive(program))
        isRefused = true
        hub.end(streamOf(hub), "permission_denied")
        waitFor { refusals.isNotEmpty() }
        assertEquals(listOf("permission_denied" to false), refusals)
        assertTrue(relay.isActive)
        send(program, port, "b")
        Thread.sleep(200)
        assertEquals(1, tries)
        now += 1000
        send(program, port, "c")
        waitFor { tries == 2 }
        send(program, port, "d")
        Thread.sleep(200)
        assertEquals(2, tries)
        isRefused = false
        now += 1000
        send(program, port, "e")
        assertEquals("e", receive(program))
        assertTrue(relay.isActive)
    }

    @Test
    fun aStreamTheFarEndClosedIsOpenedAgainByTheNextDatagram() {
        val hub = FakeConnectHub()
        val port = relay { hub.open(ChannelFrames.args("id" to "u1")) }.start()
        val program = program()
        send(program, port, "a")
        assertEquals("a", receive(program))
        hub.end(streamOf(hub))
        send(program, port, "b")
        assertEquals("b", receive(program))
        assertEquals(2, opensOf(hub).size)
        assertTrue(refusals.isEmpty())
    }

    @Test
    fun closingEndsTheStreamAndFreesThePort() {
        val hub = FakeConnectHub()
        val relay = relay { hub.open(ChannelFrames.args("id" to "u1")) }
        val port = relay.start()
        relay.close()
        assertFalse(relay.isActive)
        assertEquals(1, hub.closed.size)
        DatagramSocket(InetSocketAddress(InetAddress.getByName("127.0.0.1"), port)).close()
    }

    private fun relay(open: () -> ChannelResult<ChannelStream>): PortForwardUdpRelay =
        PortForwardUdpRelay("b1/u1", open, 0, { refusal, isEnded ->
            synchronized(refusals) { refusals += refusal.code to isEnded }
        }) { now }.also { opened += it }

    private fun program(): DatagramSocket =
        DatagramSocket(InetSocketAddress(InetAddress.getByName("127.0.0.1"), 0)).also {
            it.soTimeout = EVENT_BOUND_MILLIS
            opened += it
        }

    private fun send(program: DatagramSocket, port: Int, text: String) {
        val bytes = text.toByteArray()
        program.send(DatagramPacket(bytes, bytes.size, InetSocketAddress("127.0.0.1", port)))
    }

    private fun receive(program: DatagramSocket): String =
        receiveOrNull(program) ?: throw AssertionError("no reply came")

    private fun receiveOrNull(program: DatagramSocket, timeoutMillis: Int = EVENT_BOUND_MILLIS): String? {
        val buffer = ByteArray(2048)
        val packet = DatagramPacket(buffer, buffer.size)
        program.soTimeout = timeoutMillis
        return try {
            program.receive(packet)
            String(buffer, 0, packet.length)
        } catch (_: SocketTimeoutException) {
            null
        }
    }

    private fun reply(source: Int, text: String): ByteArray =
        ByteBuffer.allocate(2 + text.length).putShort(source.toShort()).put(text.toByteArray()).array()

    private fun framesOf(hub: FakeConnectHub): List<ByteArray> = synchronized(hub) { hub.frames.toList() }

    private fun opensOf(hub: FakeConnectHub) = synchronized(hub) { hub.opens.toList() }

    private fun sourceOf(frame: ByteArray): Int = ByteBuffer.wrap(frame, 0, 2).short.toInt() and 0xffff

    private fun streamOf(hub: FakeConnectHub): Int = opensOf(hub).last()["stream"]!!.jsonPrimitive.content.toInt()

    private fun waitFor(condition: () -> Boolean) {
        val deadline = System.currentTimeMillis() + EVENT_BOUND_MILLIS
        while (!condition()) {
            if (System.currentTimeMillis() > deadline) fail("the condition did not hold in $EVENT_BOUND_MILLIS ms")
            Thread.sleep(10)
        }
    }

    private companion object {
        const val EVENT_BOUND_MILLIS = 30_000
        const val QUIET_MILLIS = 1000
    }
}
