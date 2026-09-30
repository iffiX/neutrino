package io.github.iffix.neutrino.design

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.google.zxing.BarcodeFormat
import com.google.zxing.EncodeHintType
import com.google.zxing.common.BitMatrix
import com.google.zxing.qrcode.QRCodeWriter
import com.google.zxing.qrcode.decoder.ErrorCorrectionLevel

/**
 * A QR code of some text: dark modules on white inside a two-module quiet zone, whatever the
 * palette, so any scanner reads it.
 *
 * @param text What the code holds.
 * @param description What a screen reader says it is.
 * @param modifier Placement.
 * @param size The edge of the square.
 */
@Composable
fun QrCodeImage(text: String, description: String, modifier: Modifier = Modifier, size: Dp = 176.dp) {
    val palette = NeutrinoTheme.palette
    val matrix = remember(text) { qrMatrixOf(text) }
    val shape = RoundedCornerShape(10.dp)
    Canvas(
        modifier = modifier
            .size(size)
            .clip(shape)
            .border(1.dp, palette.border, shape)
            .semantics { contentDescription = description },
    ) {
        drawRect(Color.White)
        val quiet = 2
        val cell = this.size.minDimension / (matrix.width + quiet * 2)
        for (y in 0 until matrix.height) {
            for (x in 0 until matrix.width) {
                if (matrix[x, y]) {
                    drawRect(
                        Color.Black,
                        topLeft = Offset((x + quiet) * cell, (y + quiet) * cell),
                        size = Size(cell + 0.5f, cell + 0.5f),
                    )
                }
            }
        }
    }
}

/**
 * The modules of a QR code of some text, without a quiet zone.
 *
 * @param text What the code holds.
 * @return The matrix.
 */
fun qrMatrixOf(text: String): BitMatrix = QRCodeWriter().encode(
    text,
    BarcodeFormat.QR_CODE,
    0,
    0,
    mapOf(
        EncodeHintType.MARGIN to 0,
        EncodeHintType.ERROR_CORRECTION to ErrorCorrectionLevel.M,
        EncodeHintType.CHARACTER_SET to "UTF-8",
    ),
)
