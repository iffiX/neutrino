package io.github.iffix.neutrino.scan

import io.github.iffix.neutrino.SCAN_REGION_FRACTION
import kotlin.math.roundToInt

/**
 * The square of a camera frame the scanner decodes, in the frame's pixels.
 *
 * @property left The square's left edge.
 * @property top The square's top edge.
 * @property side The square's side.
 */
data class QrScanRegion(val left: Int, val top: Int, val side: Int) {
    companion object {
        /**
         * The square centred in a frame, its side a part of the frame's shorter side; the
         * square is the same however the frame is turned.
         *
         * @param width The frame's width.
         * @param height The frame's height.
         * @param fraction The square's side over the frame's shorter side.
         * @return The square.
         * @throws IllegalArgumentException When the frame is empty or the fraction is not in (0, 1].
         */
        fun centred(width: Int, height: Int, fraction: Float = SCAN_REGION_FRACTION): QrScanRegion {
            require(width > 0 && height > 0) { "a frame has a width and a height" }
            require(fraction > 0f && fraction <= 1f) { "the fraction is in (0, 1]" }
            val side = (minOf(width, height) * fraction).roundToInt().coerceAtLeast(1)
            return QrScanRegion((width - side) / 2, (height - side) / 2, side)
        }
    }
}
