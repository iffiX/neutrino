package io.github.iffix.neutrino.remotedesktop

import org.junit.Assert.assertEquals
import org.junit.Test

class RemoteDesktopCodecTest {
    @Test
    fun aPhoneCoreWithHwcodecOffersEveryCodec() {
        assertEquals(
            listOf(
                RemoteDesktopCodec.AUTO,
                RemoteDesktopCodec.VP8,
                RemoteDesktopCodec.VP9,
                RemoteDesktopCodec.AV1,
                RemoteDesktopCodec.H264,
                RemoteDesktopCodec.H265,
            ),
            RemoteDesktopCodec.offered("arm64-v8a"),
        )
    }

    @Test
    fun theEmulatorCoreOffersNoH264OrH265() {
        assertEquals(
            listOf(RemoteDesktopCodec.AUTO, RemoteDesktopCodec.VP8, RemoteDesktopCodec.VP9, RemoteDesktopCodec.AV1),
            RemoteDesktopCodec.offered("x86_64"),
        )
    }

    @Test
    fun anUnknownNameIsAuto() {
        assertEquals(RemoteDesktopCodec.H265, RemoteDesktopCodec.of("h265"))
        assertEquals(RemoteDesktopCodec.AUTO, RemoteDesktopCodec.of("mpeg2"))
        assertEquals(RemoteDesktopQuality.BALANCED, RemoteDesktopQuality.of(""))
    }
}
