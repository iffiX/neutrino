package io.github.iffix.neutrino.overlay

import io.github.iffix.neutrino.channel.ChannelOverlay
import io.github.iffix.neutrino.channel.Samples
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class OverlayChoiceTest {
    private val netbird = ChannelOverlay(provider = "netbird", setupKey = "k")
    private val easytier =
        ChannelOverlay(provider = "easytier", networkName = "n", networkSecret = "s", peer = "tcp://p:1")
    private val both = Samples.binding.copy(overlays = listOf(netbird, easytier), isOverlayWanted = true)

    @Test
    fun withTwoNetworksTheFirstIsJoined() {
        assertEquals("netbird", OverlayChoice.decide(both, running = null, channelDownForMillis = null))
    }

    @Test
    fun thePickedNetworkIsPreferred() {
        assertEquals("easytier", OverlayChoice.decide(both.copy(overlayChoice = "easytier"), null, null))
    }

    @Test
    fun aChannelLostForThirtySecondsMovesToTheNext() {
        assertEquals("netbird", OverlayChoice.decide(both, "netbird", 30_000))
        assertEquals("easytier", OverlayChoice.decide(both, "netbird", 30_001))
        assertEquals("netbird", OverlayChoice.decide(both, "easytier", 45_000))
    }

    @Test
    fun aNetworkNoLongerPublishedIsLeftForThePreferred() {
        val onlyEasyTier = both.copy(overlays = listOf(easytier))
        assertEquals("easytier", OverlayChoice.decide(onlyEasyTier, "netbird", null))
    }

    @Test
    fun withOneNetworkNothingMoves() {
        val one = both.copy(overlays = listOf(netbird))
        assertEquals("netbird", OverlayChoice.decide(one, "netbird", 120_000))
    }

    @Test
    fun noWishOrNoNetworkRunsNothing() {
        assertNull(OverlayChoice.decide(both.copy(isOverlayWanted = false), "netbird", null))
        assertNull(OverlayChoice.decide(both.copy(overlays = emptyList()), null, null))
    }

    @Test
    fun aPickTheHubNoLongerPublishesFallsBackToTheFirst() {
        assertEquals(netbird, OverlayChoice.preferred(both.copy(overlayChoice = "wireguard")))
    }
}
