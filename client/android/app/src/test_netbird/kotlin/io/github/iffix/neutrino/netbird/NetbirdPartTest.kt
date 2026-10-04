package io.github.iffix.neutrino.netbird

import io.github.iffix.neutrino.EDITION_FEATURE_NETBIRD
import io.github.iffix.neutrino.Edition
import io.github.iffix.neutrino.RepositoryFiles
import io.github.iffix.neutrino.channel.ChannelOverlay
import io.github.iffix.neutrino.channel.Samples
import io.github.iffix.neutrino.overlay.OverlayChoice
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class NetbirdPartTest {
    @Test
    fun theTableFindsThePartByItsProvider() {
        assertTrue(Edition.hasFeature(EDITION_FEATURE_NETBIRD))
        assertSame(NetbirdPart, Edition.overlayPart("netbird"))
    }

    @Test
    fun theAboutCardNamesTheReleaseTheBuildScriptPins() {
        val script = RepositoryFiles.text("packaging/build/build_core_netbird.py")
        val tag = Regex("""NETBIRD_MOBILE_TAG = "v([0-9.]+)"""").find(script)?.groupValues?.get(1)
        assertEquals(tag, NetbirdPart.carriedCore.version)
        assertEquals("https://github.com/netbirdio/netbird/tree/v$tag", NetbirdPart.carriedCore.sourceUrl)
        assertEquals("", NetbirdPart.carriedCore.patchUrl)
    }

    @Test
    fun withNoHubAddressNetBirdTakesAListedAddressInsideItsNetworkBeforeTheName() {
        val netbird = ChannelOverlay(provider = "netbird", setupKey = "k", fqdn = "hub.netbird.cloud")
        val binding = Samples.binding.copy(overlays = listOf(netbird))
        assertEquals("https://100.72.4.1:8443", OverlayChoice.hubUrl(binding, netbird))
        val lanOnly = binding.copy(gatewayUrls = listOf("https://192.168.100.1:8443"))
        assertEquals("https://hub.netbird.cloud:8443", OverlayChoice.hubUrl(lanOnly, netbird))
    }

    @Test
    fun aSetupKeyMakesItUsable() {
        val overlay = ChannelOverlay(provider = "netbird", setupKey = "k", fqdn = "hub.netbird.cloud")
        assertTrue(overlay.isUsable)
        assertFalse(overlay.copy(setupKey = " ").isUsable)
        assertEquals("NetBird", overlay.title)
        assertEquals("hub.netbird.cloud", NetbirdPart.hubName(overlay))
    }
}
