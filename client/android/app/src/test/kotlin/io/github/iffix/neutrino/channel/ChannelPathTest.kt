package io.github.iffix.neutrino.channel

import java.net.InetAddress
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ChannelPathTest {
    private val lan = ChannelLocalNetwork(InetAddress.getByName("192.168.100.7"), 24)
    private val tunnel = ChannelLocalNetwork(InetAddress.getByName("10.126.126.7"), 24)
    private val overlay = ChannelOverlayRoute("https://10.126.126.1:8443", "easytier", tunnel)
    private val relay = "https://203.0.113.5:18443"
    private val sakurafrp = "https://frp-cat.example.org:30443"
    private val openfrp = "https://frp-dog.example.org:21443"
    private val servers =
        mapOf(ChannelPath.SSH_RELAY to relay, ChannelPath.SAKURAFRP to sakurafrp, ChannelPath.OPENFRP to openfrp)

    private fun pathOf(url: String) = ChannelPath.of(url, overlay, servers, listOf(lan, tunnel))

    @Test
    fun eachCandidatesPathIsKnownBeforeItsHello() {
        assertEquals(ChannelPath.EASYTIER, pathOf("https://10.126.126.1:8443"))
        assertEquals(ChannelPath.EASYTIER, pathOf("https://10.126.126.9:8443"))
        assertEquals(ChannelPath.SSH_RELAY, pathOf(relay))
        assertEquals(ChannelPath.SAKURAFRP, pathOf(sakurafrp))
        assertEquals(ChannelPath.OPENFRP, pathOf(openfrp))
        assertEquals(ChannelPath.DIRECT, pathOf("https://frp-cat.example.org:30444"))
        assertEquals(ChannelPath.LAN, pathOf("https://192.168.100.1:8443"))
        assertEquals(ChannelPath.DIRECT, pathOf("https://198.51.100.4:8443"))
        assertEquals(ChannelPath.DIRECT, pathOf("https://hub.example.org:8443"))
        assertEquals(ChannelPath.LAN, ChannelPath.of("https://192.168.100.1:8443", null, emptyMap(), listOf(lan)))
        val unnamed = mapOf(ChannelPath.SAKURAFRP to "")
        assertEquals(ChannelPath.DIRECT, ChannelPath.of("https://198.51.100.4:8443", null, unnamed, listOf(lan)))
    }

    @Test
    fun thePathsRankLanThenDirectThenTheNetworksThenTheServers() {
        assertTrue(ChannelPath.LAN.rank < ChannelPath.DIRECT.rank)
        assertTrue(ChannelPath.DIRECT.rank < ChannelPath.NETBIRD.rank)
        assertEquals(ChannelPath.NETBIRD.rank, ChannelPath.EASYTIER.rank)
        assertTrue(ChannelPath.EASYTIER.rank < ChannelPath.SSH_RELAY.rank)
        assertEquals(ChannelPath.SSH_RELAY.rank, ChannelPath.SAKURAFRP.rank)
        assertEquals(ChannelPath.SSH_RELAY.rank, ChannelPath.OPENFRP.rank)
        assertEquals(
            listOf("lan", "direct", "netbird", "easytier", "ssh_relay", "sakurafrp", "openfrp"),
            ChannelPath.entries.map { it.wireName },
        )
    }

    @Test
    fun aNetworkHoldsOnlyAddressesOfItsFamilyWithinItsPrefix() {
        assertTrue(lan.holds(InetAddress.getByName("192.168.100.250")))
        assertTrue(!lan.holds(InetAddress.getByName("192.168.101.1")))
        assertTrue(!lan.holds(InetAddress.getByName("fe80::1")))
        val v6 = ChannelLocalNetwork(InetAddress.getByName("fd00:1:2:3::7"), 64)
        assertTrue(v6.holds(InetAddress.getByName("fd00:1:2:3::1")))
        assertTrue(!v6.holds(InetAddress.getByName("fd00:1:2:4::1")))
        assertEquals(ChannelPath.LAN, ChannelPath.of("https://[fd00:1:2:3::1]:8443", null, emptyMap(), listOf(v6)))
    }
}
