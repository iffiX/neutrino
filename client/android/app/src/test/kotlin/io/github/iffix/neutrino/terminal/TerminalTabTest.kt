package io.github.iffix.neutrino.terminal

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TerminalTabTest {
    private val open = TerminalTab("s1", "b1", "d1", "box", phase = TerminalPhase.OPEN)

    @Test
    fun theSwitchesActOnAnOpenTabThisPhoneOwns() {
        assertTrue(open.canPersist)
    }

    @Test
    fun theSwitchesAreDisabledOnATabSomeoneElseOpened() {
        assertFalse(open.copy(isOwned = false, owner = "hub", ownerName = "home").canPersist)
    }

    @Test
    fun theSwitchesAreDisabledWhileTheTabIsNotOpen() {
        for (phase in TerminalPhase.entries.filter { it != TerminalPhase.OPEN }) {
            assertFalse(phase.name, open.copy(phase = phase).canPersist)
        }
    }

    @Test
    fun theReasonNamesTheOwnerElseTheStamp() {
        assertEquals("home", open.copy(owner = "hub", ownerName = "home").ownerLabel)
        assertEquals("client:7", open.copy(owner = "client:7").ownerLabel)
    }

    @Test
    fun aKeptSessionTakesTwoPressesToEnd() {
        assertFalse(open.isKept)
        assertTrue(open.copy(isPersistent = true).isKept)
        assertTrue(open.copy(isShared = true).isKept)
    }
}
