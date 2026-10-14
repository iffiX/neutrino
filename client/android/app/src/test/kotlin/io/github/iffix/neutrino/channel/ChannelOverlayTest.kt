package io.github.iffix.neutrino.channel

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ChannelOverlayTest {
    @Test
    fun aNetBirdObjectIsUsableWithItsSetupKey() {
        val overlay = ChannelOverlay(provider = "netbird", setupKey = "k", fqdn = "hub.netbird.cloud")
        assertTrue(overlay.isUsable)
        assertFalse(overlay.copy(setupKey = " ").isUsable)
        assertEquals("NetBird", overlay.title)
    }

    @Test
    fun anUnknownProviderIsNotUsableAndGoesByItsName() {
        val overlay = ChannelOverlay(provider = "wireguard")
        assertFalse(overlay.isUsable)
        assertEquals("wireguard", overlay.title)
    }
}
