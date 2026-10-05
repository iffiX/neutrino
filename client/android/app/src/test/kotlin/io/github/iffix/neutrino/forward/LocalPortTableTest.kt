package io.github.iffix.neutrino.forward

import io.github.iffix.neutrino.CLIENT_SETTINGS_KEY_LOCAL_PORTS
import io.github.iffix.neutrino.FakeSharedPreferences
import io.github.iffix.neutrino.LocalPortTakenException
import io.github.iffix.neutrino.channel.ChannelResult
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class LocalPortTableTest {
    private val preferences = FakeSharedPreferences()
    private val busy = mutableSetOf<Int>()

    private val probes = mutableListOf<Pair<Int, Boolean>>()

    private fun table() = LocalPortTable(preferences) { port, isKept ->
        probes += port to isKept
        port !in busy
    }

    @Test
    fun autoTakesTheEntrysOwnPortWhenFree() {
        assertEquals(8000, table().portFor("b1/w1", 8000))
    }

    @Test
    fun autoFallsBackFrom20000Up() {
        val table = table()
        assertEquals(8000, table.portFor("b1/w1", 8000))
        assertEquals(20000, table.portFor("b2/w1", 8000))
        busy += 20001
        assertEquals(20002, table.portFor("b3/w1", 8000))
    }

    @Test
    fun autoSkipsABusyOrLowPort() {
        busy += 8000
        val table = table()
        assertEquals(20000, table.portFor("b1/w1", 8000))
        assertEquals(20001, table.portFor("b1/ssh", 22))
    }

    @Test
    fun aPickIsKeptForLaterForwardsAndAfterARestart() {
        val first = table()
        busy += 8000
        assertEquals(20000, first.portFor("b1/w1", 8000))
        busy.clear()
        assertEquals(20000, first.portFor("b1/w1", 8000))
        assertEquals(20000, table().portFor("b1/w1", 8000))
        assertEquals(LocalPortChoice(port = 20000), table().choiceOf("b1/w1"))
    }

    @Test
    fun aFixedNumberIsTheEntrysPort() {
        val table = table()
        assertEquals(ChannelResult.Ok(Unit), table.configure("b1/w1", LocalPortChoice(isFixed = true, port = 9000)))
        assertEquals(9000, table.portFor("b1/w1", 8000))
        assertEquals(LocalPortChoice(isFixed = true, port = 9000), table().choiceOf("b1/w1"))
    }

    @Test
    fun aFixedNumberAnotherEntryHoldsIsRefused() {
        val table = table()
        table.portFor("b1/w1", 8000)
        val answer = table.configure("b2/w1", LocalPortChoice(isFixed = true, port = 8000))
        assertEquals("port_taken", (answer as ChannelResult.Refused).code)
        assertEquals("8000", answer.wordParams["port"])
        assertEquals(LocalPortChoice(), table.choiceOf("b2/w1"))
    }

    @Test
    fun fixingItsOwnPickIsKept() {
        val table = table()
        table.portFor("b1/w1", 8000)
        assertEquals(ChannelResult.Ok(Unit), table.configure("b1/w1", LocalPortChoice(isFixed = true, port = 8000)))
    }

    @Test
    fun autoPicksAroundAFixedNumber() {
        val table = table()
        table.configure("b1/w1", LocalPortChoice(isFixed = true, port = 8000))
        assertEquals(20000, table.portFor("b2/w1", 8000))
    }

    @Test
    fun backToAutoFromFixedPicksAgain() {
        val table = table()
        table.configure("b1/w1", LocalPortChoice(isFixed = true, port = 9000))
        table.configure("b1/w1", LocalPortChoice())
        assertEquals(LocalPortChoice(), table.choiceOf("b1/w1"))
        assertEquals(8000, table.portFor("b1/w1", 8000))
    }

    @Test(expected = IllegalArgumentException::class)
    fun aFixedNumberUnderTheFloorThrows() {
        table().configure("b1/w1", LocalPortChoice(isFixed = true, port = 80))
    }

    @Test
    fun leavingAHubDropsItsEntries() {
        val table = table()
        table.portFor("b1/w1", 8000)
        table.portFor("b2/w1", 8000)
        table.forget("b1")
        assertTrue("b1/w1" !in table.choices.value)
        assertEquals(8000, table.portFor("b3/w1", 8000))
    }

    @Test
    fun aPortIsFreeOnlyWhenNothingListensOnItOnAnyAddress() {
        ServerSocket(0, 50, InetAddress.getByName("0.0.0.0")).use { everywhere ->
            assertFalse(LocalPortTable.isPortFree(everywhere.localPort))
        }
        ServerSocket(0, 50, InetAddress.getByName("127.0.0.1")).use { loopback ->
            assertFalse(LocalPortTable.isPortFree(loopback.localPort))
        }
        val free = ServerSocket(0).use { it.localPort }
        assertTrue(LocalPortTable.isPortFree(free))
    }

    @Test
    fun aKeptPortIsProbedAgainBeforeEveryForward() {
        val table = table()
        assertEquals(8000, table.portFor("b1/w1", 8000))
        assertEquals(listOf(8000 to false), probes)
        assertEquals(8000, table.portFor("b1/w1", 8000))
        assertEquals(8000 to true, probes.last())
    }

    @Test
    fun aTakenAutoPickIsPickedAgainAndTheNewPortKept() {
        val table = table()
        assertEquals(8000, table.portFor("b1/w1", 8000))
        busy += 8000
        assertEquals(20000, table.portFor("b1/w1", 8000))
        assertEquals(LocalPortChoice(isFixed = false, port = 20000), table.choiceOf("b1/w1"))
        busy -= 8000
        assertEquals(20000, table.portFor("b1/w1", 8000))
    }

    @Test
    fun aTakenFixedPortIsRefusedAndKept() {
        val table = table()
        table.configure("b1/w1", LocalPortChoice(isFixed = true, port = 28080))
        busy += 28080
        try {
            table.portFor("b1/w1", 8000)
            fail("a fixed port another program listens on was handed out")
        } catch (error: LocalPortTakenException) {
            assertEquals(28080, error.port)
        }
        assertEquals(LocalPortChoice(isFixed = true, port = 28080), table.choiceOf("b1/w1"))
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
        ServerSocket(0, 50, InetAddress.getByName("0.0.0.0")).use { everywhere ->
            assertFalse(LocalPortTable.isPortFree(everywhere.localPort, isKept = true))
        }
    }

    @Test
    fun aTcpAndAUdpEntryHoldOneNumber() {
        val udpBusy = mutableSetOf<Int>()
        val table = LocalPortTable(preferences, { port, _ -> port !in udpBusy }) { port, _ -> port !in busy }
        assertEquals(8053, table.portFor("b1/dns", 8053))
        assertEquals(8053, table.portFor("b1/dns_udp", 8053, "udp"))
        assertEquals("udp", table.choiceOf("b1/dns_udp").protocol)
        assertEquals(20000, table.portFor("b1/other_udp", 8053, "udp"))
        udpBusy += 8053
        assertEquals(8053, table.portFor("b1/dns", 8053))
        assertEquals(20001, table.portFor("b1/dns_udp", 8053, "udp"))
    }

    @Test
    fun aFixedNumberTakenOnlyWithinOneProtocol() {
        val table = table()
        table.configure("b1/dns", LocalPortChoice(isFixed = true, port = 28053))
        assertEquals(
            ChannelResult.Ok(Unit),
            table.configure("b1/dns_udp", LocalPortChoice(isFixed = true, port = 28053), "udp"),
        )
        val refused = table.configure("b1/other", LocalPortChoice(isFixed = true, port = 28053))
        assertEquals("port_taken", (refused as ChannelResult.Refused).code)
        val refusedUdp = table.configure("b1/other_udp", LocalPortChoice(isFixed = true, port = 28053), "udp")
        assertEquals("port_taken", (refusedUdp as ChannelResult.Refused).code)
    }

    @Test
    fun aStoredEntryWithNoProtocolReadsAsTcp() {
        preferences.edit().putString(
            CLIENT_SETTINGS_KEY_LOCAL_PORTS,
            """{"b1/p1":{"is_fixed":true,"port":28080}}""",
        ).apply()
        val table = table()
        assertEquals(LocalPortChoice(isFixed = true, port = 28080, protocol = "tcp"), table.choiceOf("b1/p1"))
        assertEquals(
            ChannelResult.Ok(Unit),
            table.configure("b1/p1_udp", LocalPortChoice(isFixed = true, port = 28080), "udp"),
        )
    }

    @Test
    fun theUdpProbeBindsUdpSockets() {
        DatagramSocket(InetSocketAddress(InetAddress.getByName("0.0.0.0"), 0)).use { everywhere ->
            assertFalse(LocalPortTable.isUdpPortFree(everywhere.localPort))
        }
        DatagramSocket(InetSocketAddress(InetAddress.getByName("127.0.0.1"), 0)).use { loopback ->
            assertFalse(LocalPortTable.isUdpPortFree(loopback.localPort))
        }
        ServerSocket(0, 50, InetAddress.getByName("0.0.0.0")).use { tcp ->
            assertTrue(LocalPortTable.isUdpPortFree(tcp.localPort))
        }
    }
}
