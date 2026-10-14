package io.github.iffix.neutrino.netbird

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

class NetbirdRoutesTest {
    @Test
    fun aListIsSplitTrimmedAndSorted() {
        assertEquals(
            listOf("100.64.0.0/10", "192.168.1.0/24", "192.168.10.0/24"),
            NetbirdRoutes.parse(" 192.168.10.0/24;100.64.0.0/10;;192.168.1.0/24 "),
        )
    }

    @Test
    fun nothingIsAnEmptyList() {
        assertEquals(emptyList<String>(), NetbirdRoutes.parse(null))
        assertEquals(emptyList<String>(), NetbirdRoutes.parse(""))
    }

    @Test
    fun theSameRoutesInAnotherOrderAreNoChange() {
        assertEquals(
            NetbirdRoutes.parse("100.64.0.0/10;192.168.10.0/24"),
            NetbirdRoutes.parse("192.168.10.0/24;100.64.0.0/10;192.168.10.0/24"),
        )
    }

    @Test
    fun anAddedOrWithdrawnRouteIsAChange() {
        val before = NetbirdRoutes.parse("100.64.0.0/10")
        assertNotEquals(before, NetbirdRoutes.parse("100.64.0.0/10;192.168.10.0/24"))
        assertEquals(before, NetbirdRoutes.parse("100.64.0.0/10;"))
        assertNotEquals(NetbirdRoutes.parse("100.64.0.0/10;192.168.10.0/24"), before)
    }
}
