package io.github.iffix.neutrino.forward

import io.github.iffix.neutrino.CLIENT_SETTINGS_KEY_LOCAL_PORTS
import io.github.iffix.neutrino.FakeSharedPreferences
import io.github.iffix.neutrino.LocalPortTakenException
import io.github.iffix.neutrino.channel.ChannelResult
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class LocalPortTableTest {
    private val preferences = FakeSharedPreferences()
    private val busy = mutableSetOf<Pair<Int, String>>()
    private val probes = mutableListOf<Triple<Int, String, Boolean>>()

    private fun table() = LocalPortTable(preferences) { port, protocol, isKept ->
        probes += Triple(port, protocol, isKept)
        (port to protocol) !in busy
    }

    private val hubNumbers = mapOf("b1/gitea_d1_web" to (27311 to "tcp"), "b1/gitea_d1_ssh" to (30418 to "tcp"))

    @Test
    fun anAppEntryListensOnTheHubsNumber() {
        assertEquals(27311, table().portForEntry("b1/gitea_d1_web", 27311, "tcp"))
        assertEquals(Triple(27311, "tcp", true), probes.single())
    }

    @Test
    fun thePersonsNumberWins() {
        val table = table()
        assertEquals(ChannelResult.Ok(Unit), table.configure("b1/gitea_d1_web", 28080, "tcp", hubNumbers))
        assertEquals(28080, table.portForEntry("b1/gitea_d1_web", 27311, "tcp"))
        assertEquals(28080, table().numberOf("b1/gitea_d1_web"))
        assertEquals(ChannelResult.Ok(Unit), table.configure("b1/gitea_d1_web", null, "tcp", hubNumbers))
        assertNull(table.numberOf("b1/gitea_d1_web"))
        assertEquals(27311, table.portOf("b1/gitea_d1_web", 27311))
    }

    @Test
    fun aNumberAnotherEntryHoldsAsItsHubNumberOrInTheTableIsRefused() {
        val table = table()
        val answer = table.configure("b1/gitea_d1_web", 30418, "tcp", hubNumbers)
        assertEquals("port_taken", (answer as ChannelResult.Refused).code)
        assertEquals("30418", answer.wordParams["port"])
        table.configure("b2/x_web", 28080, "tcp", hubNumbers)
        assertEquals(
            "port_taken",
            (table.configure("b1/gitea_d1_web", 28080, "tcp", hubNumbers) as ChannelResult.Refused).code,
        )
    }

    @Test
    fun aTcpEntryAndAUdpEntryCanHoldOneNumber() {
        val table = table()
        table.configure("b1/a_port_5000", 28080, "tcp", hubNumbers)
        assertEquals(ChannelResult.Ok(Unit), table.configure("b1/a_port_5000_udp", 28080, "udp", hubNumbers))
    }

    @Test(expected = IllegalArgumentException::class)
    fun aNumberUnderTheFloorThrows() {
        table().configure("b1/gitea_d1_web", 80, "tcp", hubNumbers)
    }

    @Test
    fun anEntrysNumberAnotherProgramHoldsIsRefusedAndNeverMoves() {
        busy += 27311 to "tcp"
        try {
            table().portForEntry("b1/gitea_d1_web", 27311, "tcp")
            fail("a held number was handed out")
        } catch (error: LocalPortTakenException) {
            assertEquals(27311, error.port)
        }
        assertNull(table().numberOf("b1/gitea_d1_web"))
    }

    @Test
    fun picksStartAt20000() {
        val table = table()
        assertEquals(20000, table.pickFor("b1/#panel", "tcp"))
        busy += 20001 to "tcp"
        assertEquals(20002, table.pickFor("b1/rdp_d1", "tcp"))
        assertEquals(20000, table().pickFor("b1/#panel", "tcp"))
    }

    @Test
    fun aKeptPickAnotherProgramHoldsIsPickedAgain() {
        val table = table()
        assertEquals(20000, table.pickFor("b1/#panel", "tcp"))
        busy += 20000 to "tcp"
        assertEquals(20001, table.pickFor("b1/#panel", "tcp"))
        assertEquals(20001, table().pickFor("b1/#panel", "tcp"))
    }

    @Test
    fun leavingAHubDropsItsEntries() {
        val table = table()
        table.configure("b1/gitea_d1_web", 28080, "tcp", hubNumbers)
        table.pickFor("b2/#panel", "tcp")
        table.forget("b1")
        assertEquals(setOf("b2/#panel"), table.choices.value.keys)
    }

    @Test
    fun aStoredEntryWithNoProtocolReadsAsTcp() {
        preferences.edit().putString(
            CLIENT_SETTINGS_KEY_LOCAL_PORTS,
            """{"b1/p1":{"is_fixed":true,"port":28080}}""",
        ).apply()
        assertEquals(LocalPortChoice(isFixed = true, port = 28080, protocol = "tcp"), table().choices.value["b1/p1"])
    }

    @Test
    fun aPortIsFreeOnlyWhenNothingListensOnItOnAnyAddressForItsProtocol() {
        ServerSocket(0, 50, InetAddress.getByName("0.0.0.0")).use { everywhere ->
            assertFalse(LocalPortTable.isPortFree(everywhere.localPort, "tcp"))
        }
        ServerSocket(0, 50, InetAddress.getByName("127.0.0.1")).use { loopback ->
            assertFalse(LocalPortTable.isPortFree(loopback.localPort, "tcp"))
        }
        val port = ServerSocket(0, 50, InetAddress.getByName("0.0.0.0")).use { it.localPort }
        DatagramSocket(port, InetAddress.getByName("127.0.0.1")).use {
            assertFalse(LocalPortTable.isPortFree(port, "udp"))
            assertTrue(LocalPortTable.isPortFree(port, "tcp"))
        }
    }

    @Test
    fun theAppsOwnLingeringConnectionsDoNotTakeAKeptPortWhileAnotherListenerDoes() {
        val port = ServerSocket(0, 50, InetAddress.getByName("127.0.0.1")).use { listener ->
            Socket("127.0.0.1", listener.localPort).use { client ->
                listener.accept().use { served -> served.close() }
                client.getInputStream().read()
            }
            listener.localPort
        }
        assertFalse("the closed connection lingers in TIME_WAIT", LocalPortTable.isPortFree(port))
        assertTrue(LocalPortTable.isPortFree(port, isKept = true))
        ServerSocket(port, 50, InetAddress.getByName("127.0.0.1")).use {
            assertFalse(LocalPortTable.isPortFree(port, isKept = true))
        }
    }
}
