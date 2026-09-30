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
            listOf(EasyTierInstance("neutrino", "10.144.144.2", 24, listOf("192.168.100.0/24"), true, "")),
            EasyTierInstance.parse(text),
        )
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
