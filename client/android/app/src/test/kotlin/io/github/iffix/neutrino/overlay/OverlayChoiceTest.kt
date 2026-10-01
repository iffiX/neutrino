package io.github.iffix.neutrino.overlay

import io.github.iffix.neutrino.channel.ChannelOverlay
import io.github.iffix.neutrino.channel.Samples
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class OverlayChoiceTest {
    private val netbird = ChannelOverlay(provider = "netbird", setupKey = "k", fqdn = "hub.netbird.cloud")
    private val easytier = ChannelOverlay(
        provider = "easytier",
        networkName = "n",
        networkSecret = "s",
        peer = "tcp://p:1",
        hubAddress = "10.126.126.1",
    )
    private val both = Samples.binding.copy(overlays = listOf(netbird, easytier))

    @Test
    fun withNoPickTheHubsFirstIsJoined() {
        assertEquals(netbird, OverlayChoice.preferred(both))
    }

    @Test
    fun thePickedNetworkIsJoined() {
        assertEquals(easytier, OverlayChoice.preferred(both.copy(overlayChoice = "easytier")))
    }

    @Test
    fun aPickTheHubNoLongerPublishesFallsBackToTheFirst() {
        assertEquals(netbird, OverlayChoice.preferred(both.copy(overlayChoice = "wireguard")))
    }

    @Test
    fun noNetworkIsNothing() {
        assertNull(OverlayChoice.preferred(both.copy(overlays = emptyList())))
    }

    @Test
    fun theHubsAddressOnANetworkTakesThePortItLastAnsweredOn() {
        assertEquals("https://hub.netbird.cloud:8443", OverlayChoice.hubUrl(both, netbird))
        assertEquals("https://10.126.126.1:8443", OverlayChoice.hubUrl(both, easytier))
    }

    @Test
    fun anAddressTheHubListsOnThatHostIsTakenAsItIs() {
        val listed = both.copy(gatewayUrls = both.gatewayUrls + "https://10.126.126.1:9443")
        assertEquals("https://10.126.126.1:9443", OverlayChoice.hubUrl(listed, easytier))
    }

    @Test
    fun aNetworkThatNamesNoHubAddressHasNone() {
        assertEquals("", OverlayChoice.hubUrl(both, easytier.copy(hubAddress = "")))
    }
}
