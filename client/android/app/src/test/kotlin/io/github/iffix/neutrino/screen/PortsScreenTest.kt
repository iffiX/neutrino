package io.github.iffix.neutrino.screen

import io.github.iffix.neutrino.channel.ChannelServiceEntry
import io.github.iffix.neutrino.channel.HubConnection
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.channel.Samples
import io.github.iffix.neutrino.design.DotTone
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Test

class PortsScreenTest {
    private fun port(payload: String, isHealthy: Boolean? = true) =
        ChannelServiceEntry("p1", "port", "dns", Json.parseToJsonElement(payload).jsonObject, isHealthy = isHealthy)

    @Test
    fun aUdpRowCarriesTheSuffixOnBothAddresses() {
        val entry = port("""{"host": "192.0.2.5", "port": 53, "protocol": "udp"}""")
        assertEquals("udp", entry.portProtocol)
        assertEquals("192.0.2.5:53/udp", portLine(entry, null))
        assertEquals("192.0.2.5:53/udp → 127.0.0.1:20053/udp", portLine(entry, "127.0.0.1:20053"))
    }

    @Test
    fun aTcpRowAndARowFromAHubThatNamesNoProtocolAreUnchanged() {
        val named = port("""{"host": "192.0.2.5", "port": 22, "protocol": "tcp"}""")
        val unnamed = port("""{"host": "192.0.2.5", "port": 22}""")
        assertEquals("tcp", unnamed.portProtocol)
        for (entry in listOf(named, unnamed)) {
            assertEquals("192.0.2.5:22", portLine(entry, null))
            assertEquals("192.0.2.5:22 → 127.0.0.1:20022", portLine(entry, "127.0.0.1:20022"))
        }
    }

    @Test
    fun onlyAFalseHealthIsUnhealthy() {
        val udp = """{"host": "192.0.2.5", "port": 53, "protocol": "udp"}"""
        assertEquals(DotTone.WAIT, entryTone(hubOf(), port(udp, isHealthy = false)))
        assertEquals(DotTone.OK, entryTone(hubOf(), port(udp, isHealthy = null)))
    }

    private fun hubOf() = HubView(
        Samples.binding,
        HubConnection.CONNECTED,
    )
}
