package io.github.iffix.neutrino.scan

import io.github.iffix.neutrino.channel.Samples
import io.github.iffix.neutrino.design.qrMatrixOf
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class QrFrameDecoderTest {
    private val scale = 4
    private val quiet = 8

    private fun frame(text: String, isInverted: Boolean = false, rowPadding: Int = 0): Triple<ByteArray, Int, Int> {
        val matrix = qrMatrixOf(text)
        val width = (matrix.width + quiet * 2) * scale
        val height = (matrix.height + quiet * 2) * scale
        val stride = width + rowPadding
        val light = if (isInverted) 0 else 255
        val dark = if (isInverted) 255 else 0
        val bytes = ByteArray(stride * height) { light.toByte() }
        for (y in 0 until height) {
            for (x in 0 until width) {
                val mx = x / scale - quiet
                val my = y / scale - quiet
                if (mx in 0 until matrix.width && my in 0 until matrix.height && matrix[mx, my]) {
                    bytes[y * stride + x] = dark.toByte()
                }
            }
        }
        return Triple(bytes, width, height)
    }

    @Test
    fun aLinkInAFrameIsRead() {
        val link = Samples.link(Samples.clientPayload)
        val (bytes, width, height) = frame(link)
        assertEquals(link, QrFrameDecoder.decode(bytes, width, height))
    }

    @Test
    fun rowsLongerThanTheFrameAreRead() {
        val (bytes, width, height) = frame("neutrino://enroll/abc", rowPadding = 16)
        assertEquals("neutrino://enroll/abc", QrFrameDecoder.decode(bytes, width, height, rowStride = width + 16))
    }

    @Test
    fun aCodeShownLightOnDarkIsRead() {
        val (bytes, width, height) = frame("neutrino://enroll/abc", isInverted = true)
        assertEquals("neutrino://enroll/abc", QrFrameDecoder.decode(bytes, width, height))
    }

    @Test
    fun aFrameWithoutACodeReadsAsNothing() {
        assertNull(QrFrameDecoder.decode(ByteArray(64 * 64) { 127 }, 64, 64))
    }
}
