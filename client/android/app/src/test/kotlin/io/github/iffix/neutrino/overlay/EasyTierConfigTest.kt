package io.github.iffix.neutrino.overlay

import io.github.iffix.neutrino.channel.ChannelOverlay
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class EasyTierConfigTest {
    @Test
    fun aManualNetworkNamesItsIdentityAndItsPeer() {
        val overlay =
            ChannelOverlay(
                provider = "easytier",
                networkName = "neutrino",
                networkSecret = "s3",
                peer = "tcp://203.0.113.7:11010",
            )
        val toml = EasyTierConfig.render(overlay, "neutrino", "pixel")
        assertTrue(toml.contains("instance_name = \"neutrino\""))
        assertTrue(toml.contains("dhcp = true"))
        assertTrue(toml.contains("[network_identity]\nnetwork_name = \"neutrino\"\nnetwork_secret = \"s3\""))
        assertTrue(toml.contains("[[peer]]\nuri = \"tcp://203.0.113.7:11010\""))
    }

    @Test
    fun aStringIsQuotedTheWayTomlReadsIt() {
        assertEquals("\"a\\\"b\\\\c\\nd\\u0001\"", EasyTierConfig.quoted("a\"b\\c\nd\u0001"))
    }
}
