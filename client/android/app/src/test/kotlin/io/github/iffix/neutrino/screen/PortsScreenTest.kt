package io.github.iffix.neutrino.screen

import io.github.iffix.neutrino.RepositoryFiles
import io.github.iffix.neutrino.channel.ChannelServiceEntry
import io.github.iffix.neutrino.channel.HubConnection
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.channel.Samples
import io.github.iffix.neutrino.design.DotTone
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PortsScreenTest {
    private val screen =
        RepositoryFiles.text("client/android/app/src/main/kotlin/io/github/iffix/neutrino/screen/PortsScreen.kt")

    private fun port(payload: String, isHealthy: Boolean? = true) =
        ChannelServiceEntry("p1", "port", "dns", Json.parseToJsonElement(payload).jsonObject, isHealthy = isHealthy)

    @Test
    fun aUdpRowCarriesTheSuffixOnBothAddresses() {
        val entry = port("""{"host": "192.0.2.5", "port": 53, "protocol": "udp"}""")
        assertEquals("udp", entry.portProtocol)
        assertEquals(listOf("192.0.2.5:53/udp"), portPieces(entry, null))
        assertEquals(listOf("192.0.2.5:53/udp", "→ 127.0.0.1:20053/udp"), portPieces(entry, "127.0.0.1:20053"))
    }

    @Test
    fun aTcpRowAndARowFromAHubThatNamesNoProtocolAreUnchanged() {
        val named = port("""{"host": "192.0.2.5", "port": 22, "protocol": "tcp"}""")
        val unnamed = port("""{"host": "192.0.2.5", "port": 22}""")
        assertEquals("tcp", unnamed.portProtocol)
        for (entry in listOf(named, unnamed)) {
            assertEquals(listOf("192.0.2.5:22"), portPieces(entry, null))
            assertEquals(listOf("192.0.2.5:22", "→ 127.0.0.1:20022"), portPieces(entry, "127.0.0.1:20022"))
        }
    }

    @Test
    fun eachPieceIsDrawnUnbrokenAndThePiecesWrapWhole() {
        val line = screen.substringAfter("private fun PortLine(pieces: List<String>) {").substringBefore("\n}")
        assertTrue(line.contains("FlowRow("))
        assertTrue(line.contains("BasicText(piece, style = NeutrinoTheme.mono, softWrap = false, maxLines = 1)"))
        assertTrue(screen.contains("PortLine(portPieces(entry, forwardedTo))"))
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
