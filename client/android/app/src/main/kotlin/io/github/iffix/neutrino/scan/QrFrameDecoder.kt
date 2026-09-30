package io.github.iffix.neutrino.scan

import com.google.zxing.BarcodeFormat
import com.google.zxing.BinaryBitmap
import com.google.zxing.DecodeHintType
import com.google.zxing.NotFoundException
import com.google.zxing.PlanarYUVLuminanceSource
import com.google.zxing.ReaderException
import com.google.zxing.common.HybridBinarizer
import com.google.zxing.qrcode.QRCodeReader

/** Finds a QR code in one camera frame's brightness plane. */
object QrFrameDecoder {
    private val hints = mapOf(
        DecodeHintType.POSSIBLE_FORMATS to listOf(BarcodeFormat.QR_CODE),
        DecodeHintType.TRY_HARDER to true,
    )

    /**
     * The text of the QR code in a frame.
     *
     * @param luminance The frame's Y plane, one byte per pixel, rows [rowStride] bytes apart.
     * @param width The frame's width in pixels.
     * @param height The frame's height in pixels.
     * @param rowStride The bytes from one row's start to the next.
     * @return The code's text, or null when the frame holds none that reads.
     */
    fun decode(luminance: ByteArray, width: Int, height: Int, rowStride: Int = width): String? {
        val source = PlanarYUVLuminanceSource(luminance, rowStride, height, 0, 0, width, height, false)
        for (bitmap in listOf(BinaryBitmap(HybridBinarizer(source)), BinaryBitmap(HybridBinarizer(source.invert())))) {
            try {
                return QRCodeReader().decode(bitmap, hints).text
            } catch (_: NotFoundException) {
                continue
            } catch (_: ReaderException) {
                continue
            }
        }
        return null
    }
}
