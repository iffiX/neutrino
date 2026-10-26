package io.github.iffix.neutrino.transport

import io.github.iffix.neutrino.TRANSPORT_RECORD_BYTES_MAX
import io.github.iffix.neutrino.TRANSPORT_RECORD_CLOSE
import io.github.iffix.neutrino.TRANSPORT_RECORD_DATA
import io.github.iffix.neutrino.channel.ChannelResult
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.DataInputStream
import java.io.IOException
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class TransportRecordTest {
    @Test
    fun aRecordIsItsTypeItsBigEndianLengthAndItsPayload() {
        val out = ByteArrayOutputStream()
        TransportRecord.write(out, TRANSPORT_RECORD_DATA, byteArrayOf(7, 8))
        assertArrayEquals(byteArrayOf(3, 0, 0, 0, 2, 7, 8), out.toByteArray())
    }

    @Test
    fun aPayloadPastTheLargestRecordIsCutIntoSeveral() {
        val out = ByteArrayOutputStream()
        TransportRecord.write(out, TRANSPORT_RECORD_DATA, ByteArray(TRANSPORT_RECORD_BYTES_MAX + 3) { 1 })
        val input = DataInputStream(ByteArrayInputStream(out.toByteArray()))
        assertEquals(TRANSPORT_RECORD_BYTES_MAX, TransportRecord.read(input)?.payload?.size)
        assertEquals(3, TransportRecord.read(input)?.payload?.size)
        assertNull(TransportRecord.read(input))
    }

    @Test
    fun aCloseWithACodeIsARefusalAndOneWithoutIsAResult() {
        val refused =
            TransportRecord(
                TRANSPORT_RECORD_CLOSE,
                """{"code":"agent_offline","params":{"device":"d1"}}""".toByteArray(),
            )
        assertEquals("agent_offline", refused.refusal?.code)
        assertEquals("d1", refused.refusal?.wordParams?.get("device"))
        val result = TransportRecord(TRANSPORT_RECORD_CLOSE, """{"code":"","params":{"exit_code":0}}""".toByteArray())
        assertNull(result.refusal)
        assertEquals(ChannelResult.Ok(result.json).value["params"].toString(), """{"exit_code":0}""")
    }

    @Test(expected = IOException::class)
    fun aStreamThatEndsInsideARecordIsBroken() {
        TransportRecord.read(DataInputStream(ByteArrayInputStream(byteArrayOf(3, 0, 0, 0, 9, 1))))
    }
}
