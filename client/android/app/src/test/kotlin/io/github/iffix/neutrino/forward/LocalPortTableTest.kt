package io.github.iffix.neutrino.forward

import io.github.iffix.neutrino.FakeSharedPreferences
import io.github.iffix.neutrino.channel.ChannelResult
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class LocalPortTableTest {
    private val preferences = FakeSharedPreferences()
    private val busy = mutableSetOf<Int>()

    private fun table() = LocalPortTable(preferences) { it !in busy }

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
}
