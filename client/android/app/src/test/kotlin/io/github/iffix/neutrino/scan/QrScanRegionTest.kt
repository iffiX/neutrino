package io.github.iffix.neutrino.scan

import org.junit.Assert.assertEquals
import org.junit.Test

class QrScanRegionTest {
    @Test
    fun theSquareIsCentredOnTheShorterSide() {
        assertEquals(QrScanRegion(582, 162, 756), QrScanRegion.centred(1920, 1080, fraction = 0.7f))
    }

    @Test
    fun aTurnedFrameGivesTheSameSquareTurned() {
        assertEquals(QrScanRegion(162, 582, 756), QrScanRegion.centred(1080, 1920, fraction = 0.7f))
    }

    @Test
    fun theWholeShorterSideIsTheLargestSquare() {
        assertEquals(QrScanRegion(420, 0, 1080), QrScanRegion.centred(1920, 1080, fraction = 1f))
    }

    @Test(expected = IllegalArgumentException::class)
    fun aFractionAboveOneIsRefused() {
        QrScanRegion.centred(1920, 1080, fraction = 1.5f)
    }
}
