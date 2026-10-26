package io.github.iffix.neutrino.transport

import io.github.iffix.neutrino.TRANSPORT_RECORD_DATA
import io.github.iffix.neutrino.channel.ChannelResult
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TransportStreamTest {
    private val transport = FakeTransport().also { it.start("/data", "ff".repeat(32)) }
    private val open = buildJsonObject {
        put("kind", "connect")
        put("id", "gitea_d1_web")
    }

    @Test
    fun anOpenNamesTheSecretTheBindingAndTheOpenRecord() {
        transport.serve = { _, end -> FakeTransport.accept(end) }
        val opened = TransportStream.open(transport, transport.secret, "b1", open)
        assertTrue(opened is ChannelResult.Ok)
        val first = transport.opens.single()
        assertEquals("open", FakeTransport.text(first, "op"))
        assertEquals("b1", FakeTransport.text(first, "binding"))
        assertEquals(open, first["open"])
    }

    @Test
    fun aRefusingCloseIsTheStreamsRefusal() {
        transport.serve =
            { _, end -> FakeTransport.refuse(end, "permission_denied", buildJsonObject { put("kind", "web") }) }
        val opened = TransportStream.open(transport, transport.secret, "b1", open)
        assertEquals("permission_denied", (opened as ChannelResult.Refused).code)
        assertEquals("web", opened.wordParams["kind"])
    }

    @Test
    fun aConnectStreamCarriesRawBytesBothWaysAfterItsAccept() {
        transport.serve = { _, end ->
            FakeTransport.accept(end)
            end.output.write("hello".toByteArray())
            val got = ByteArray(4)
            var read = 0
            while (read < 4) read += end.input.read(got, read, 4 - read)
            end.output.write(got)
        }
        val stream = (TransportStream.open(transport, transport.secret, "b1", open) as ChannelResult.Ok).value
        val first = ByteArray(5)
        var read = 0
        while (read < 5) read += stream.rawInput.read(first, read, 5 - read)
        assertArrayEquals("hello".toByteArray(), first)
        stream.rawOutput.write("ping".toByteArray())
        val back = ByteArray(4)
        read = 0
        while (read < 4) read += stream.rawInput.read(back, read, 4 - read)
        assertArrayEquals("ping".toByteArray(), back)
        stream.close()
    }

    @Test
    fun aRecordStreamCarriesRecords() {
        transport.serve = { _, end ->
            FakeTransport.accept(end)
            val record = TransportRecord.read(FakeTransport.records(end))
            if (record != null) TransportRecord.write(end.output, record.type, record.payload)
        }
        val stream = (TransportStream.open(transport, transport.secret, "b1", open) as ChannelResult.Ok).value
        assertTrue(stream.write(TRANSPORT_RECORD_DATA, "ls\n".toByteArray()))
        val echoed = stream.read()
        assertEquals(TRANSPORT_RECORD_DATA, echoed?.type)
        assertArrayEquals("ls\n".toByteArray(), echoed?.payload)
    }

    @Test
    fun aTransportThatAnswersNothingIsUnreachable() {
        transport.serve = { _, end -> end.close() }
        val opened = TransportStream.open(transport, transport.secret, "b1", open)
        assertEquals("hub_unreachable", (opened as ChannelResult.Refused).code)
    }
}
