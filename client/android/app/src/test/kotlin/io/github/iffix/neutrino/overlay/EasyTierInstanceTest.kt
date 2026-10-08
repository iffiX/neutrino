package io.github.iffix.neutrino.overlay

import org.junit.Assert.assertEquals
import org.junit.Test

class EasyTierInstanceTest {
    @Test
    fun anInstanceWithAnAddressIsRead() {
        val text = """
            {"map": {"neutrino": {
              "dev_name": "",
              "my_node_info": {"virtual_ipv4": {"address": {"addr": 177246210}, "network_length": 24}, "hostname": "pixel"},
              "routes": [{"peer_id": 1, "proxy_cidrs": ["192.168.100.0/24"]}, {"peer_id": 2, "proxy_cidrs": []}],
              "running": true,
              "error_msg": null
            }}}
        """.trimIndent()
        assertEquals(
            listOf(EasyTierInstance("neutrino", "10.144.144.2", 24, listOf("192.168.100.0/24"), emptySet(), true, "")),
            EasyTierInstance.parse(text),
        )
    }

    @Test
    fun theOtherMembersAddressesAreThePeerList() {
        val text = """
            {"map": {"neutrino": {
              "my_node_info": {"virtual_ipv4": {"address": {"addr": 177246210}, "network_length": 24}},
              "routes": [
                {"peer_id": 1, "ipv4_addr": {"address": {"addr": 177246209}, "network_length": 24}, "proxy_cidrs": []},
                {"peer_id": 2, "ipv4_addr": {"address": {"addr": 177246211}, "network_length": 24}, "proxy_cidrs": []},
                {"peer_id": 3, "ipv4_addr": null, "proxy_cidrs": []}
              ],
              "running": true
            }}}
        """.trimIndent()
        assertEquals(setOf("10.144.144.1", "10.144.144.3"), EasyTierInstance.parse(text).single().peerAddresses)
    }

    @Test
    fun anInstanceWithoutAnAddressYetHasNone() {
        val text =
            """{"map": {"c1": {"my_node_info": null, "routes": [], "running": true, "error_msg": "no peer"}}}"""
        val instance = EasyTierInstance.parse(text).single()
        assertEquals("", instance.address)
        assertEquals("no peer", instance.error)
    }

    @Test
    fun textThatDoesNotReadIsNoInstance() {
        assertEquals(emptyList<EasyTierInstance>(), EasyTierInstance.parse(null))
        assertEquals(emptyList<EasyTierInstance>(), EasyTierInstance.parse("not json"))
        assertEquals(emptyList<EasyTierInstance>(), EasyTierInstance.parse("{}"))
    }
}
