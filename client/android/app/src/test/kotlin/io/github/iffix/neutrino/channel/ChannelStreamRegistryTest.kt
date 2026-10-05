package io.github.iffix.neutrino.channel

import io.github.iffix.neutrino.CLIENT_STREAM_CREDIT_BYTES
import io.github.iffix.neutrino.CLIENT_WS_CHUNK_BYTES
import java.nio.ByteBuffer
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.async
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class ChannelStreamRegistryTest {
    private val socket = FakeChannelSocket()
    private val registry = ChannelStreamRegistry(socket)

    private fun open(hasBytes: Boolean = false) =
        (registry.open("shell", ChannelFrames.args("device_id" to "d"), hasBytes) as ChannelResult.Ok).value

    private fun frame(stream: Int, bytes: ByteArray) =
        ByteBuffer.allocate(4 + bytes.size).putInt(stream).put(bytes).array()

    @Test
    fun thisSideOpensOddIdsCountingUp() {
        assertEquals(listOf(1, 3, 5), List(3) { open().id })
        assertEquals(listOf(1, 3, 5), socket.sent("open").map { it["stream"]!!.jsonPrimitive.int })
    }

    @Test
    fun aByteStreamGrantsTheHubAWindowAtOnce() {
        open(hasBytes = true)
        assertEquals(CLIENT_STREAM_CREDIT_BYTES, socket.sent("credit").single()["bytes"]!!.jsonPrimitive.int)
    }

    @Test
    fun theHubsCloseIsTheResult() = runTest {
        val stream = open()
        registry.takeClose(ChannelInbound.Close(stream.id, "", JsonObject(mapOf("x" to JsonPrimitive(1)))))
        assertEquals(ChannelResult.Ok(JsonObject(mapOf("x" to JsonPrimitive(1)))), stream.awaitClose(1000))
    }

    @Test
    fun aCloseWithACodeIsARefusal() = runTest {
        val stream = open()
        registry.takeClose(ChannelInbound.Close(stream.id, "permission_denied", JsonObject(emptyMap())))
        assertEquals("permission_denied", (stream.awaitClose(1000) as ChannelResult.Refused).code)
    }

    @Test
    fun noCloseInTimeIsUnreachable() = runTest {
        assertEquals("hub_unreachable", (open().awaitClose(1000) as ChannelResult.Refused).code)
    }

    @Test
    fun theSocketEndingWakesEveryStream() = runTest {
        val stream = open(hasBytes = true)
        registry.endAll()
        assertEquals("hub_unreachable", (stream.awaitClose(1000) as ChannelResult.Refused).code)
        assertNull(stream.read())
        assertEquals("hub_unreachable", (registry.open("service", emptyMap()) as ChannelResult.Refused).code)
    }

    @Test
    fun aStreamTheHubOpensIsClosedKindUnknown() {
        registry.refuse(ChannelInbound.Open(2, "file"))
        val close = socket.sent("close").single()
        assertEquals("kind_unknown", close["code"]!!.jsonPrimitive.content)
        assertEquals(2, close["stream"]!!.jsonPrimitive.int)
    }

    @Test
    fun bytesReachTheirStreamAndHalfAWindowReadGrantsMore() = runTest {
        val stream = open(hasBytes = true)
        val half = ByteArray(CLIENT_STREAM_CREDIT_BYTES / 2)
        registry.takeBinary(frame(stream.id, half))
        registry.takeBinary(frame(99, byteArrayOf(1)))
        assertEquals(half.size, stream.read()?.size)
        assertEquals(
            listOf(CLIENT_STREAM_CREDIT_BYTES, half.size),
            socket.sent("credit").map {
                it["bytes"]!!.jsonPrimitive.int
            },
        )
    }

    @Test
    fun sendingWaitsForCreditAndCutsFramesToTheChunk() = runTest {
        val stream = open(hasBytes = true)
        val sending = async { stream.send(ByteArray(CLIENT_WS_CHUNK_BYTES + 10)) }
        runCurrent()
        assertTrue(socket.binaries.isEmpty())
        registry.takeCredit(ChannelInbound.Credit(stream.id, CLIENT_WS_CHUNK_BYTES * 2))
        assertEquals(ChannelResult.Ok(Unit), sending.await())
        assertEquals(listOf(4 + CLIENT_WS_CHUNK_BYTES, 4 + 10), socket.binaries.map { it.size })
        assertEquals(stream.id, ByteBuffer.wrap(socket.binaries[0]).int)
    }

    @Test
    fun noCreditInTimeFailsTheSend() = runTest {
        val stream = open(hasBytes = true)
        assertEquals("hub_unreachable", (stream.send(byteArrayOf(1)) as ChannelResult.Refused).code)
    }

    @Test
    fun aFrameTheCreditDoesNotCoverIsDroppedWithoutWaiting() = runTest {
        val stream = open(hasBytes = true)
        assertEquals(false, stream.trySend(byteArrayOf(0, 1, 2)))
        registry.takeCredit(ChannelInbound.Credit(stream.id, 5))
        assertEquals(true, stream.trySend(byteArrayOf(0, 1, 2)))
        assertEquals(false, stream.trySend(byteArrayOf(0, 1, 2)))
        assertEquals(true, stream.trySend(byteArrayOf(0, 1)))
        assertEquals(listOf(7, 6), socket.binaries.map { it.size })
    }

    @Test
    fun aReceivedFrameIsGrantedBackAtOnce() = runTest {
        val stream = open(hasBytes = true)
        registry.takeBinary(frame(stream.id, byteArrayOf(0, 9, 7, 7)))
        assertEquals(4, stream.receive()?.size)
        assertEquals(4, socket.sent("credit").last()["bytes"]!!.jsonPrimitive.int)
    }

    @Test
    fun waitingForTheFirstCreditEndsWithTheCreditOrTheStream() = runTest {
        val credited = open(hasBytes = true)
        val waiting = async { credited.awaitCredit() }
        runCurrent()
        assertTrue(waiting.isActive)
        registry.takeCredit(ChannelInbound.Credit(credited.id, 1))
        assertEquals(true, waiting.await())
        val refused = open(hasBytes = true)
        registry.takeClose(ChannelInbound.Close(refused.id, "permission_denied", JsonObject(emptyMap())))
        assertEquals(false, refused.awaitCredit())
        assertEquals("permission_denied", refused.refusal?.code)
    }

    @Test
    fun closingHereSendsOneCloseAndNoMore() = runTest {
        val stream = open()
        stream.close()
        stream.close()
        assertEquals(1, socket.sent("close").size)
        assertTrue(stream.isDone)
    }
}
