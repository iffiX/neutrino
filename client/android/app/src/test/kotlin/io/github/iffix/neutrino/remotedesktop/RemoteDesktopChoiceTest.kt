package io.github.iffix.neutrino.remotedesktop

import org.junit.Assert.assertEquals
import org.junit.Test

class RemoteDesktopChoiceTest {
    @Test
    fun theDefaultAsksForAutoAndBalanced() {
        assertEquals(
            listOf("codec-preference" to "auto", "image-quality" to "balanced"),
            RemoteDesktopChoice().options(),
        )
    }

    @Test
    fun eachCodecAndQualityMapsToRustDesksName() {
        assertEquals(
            listOf("auto", "vp8", "vp9", "av1", "h264", "h265"),
            RemoteDesktopCodec.entries.map { RemoteDesktopChoice(codec = it).options()[0].second },
        )
        assertEquals(
            listOf("balanced", "low", "best"),
            RemoteDesktopQuality.entries.map { RemoteDesktopChoice(quality = it).options()[1].second },
        )
    }
}
