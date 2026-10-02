package io.github.iffix.neutrino.terminal

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TerminalModifiersTest {
    @Test
    fun aPressHoldsAModifierAndASecondLetsItGo() {
        val held = TerminalModifiers().toggled(TerminalKey.SHIFT)
        assertTrue(held.isShift)
        assertTrue(held.isHeld(TerminalKey.SHIFT))
        assertFalse(held.toggled(TerminalKey.SHIFT).isShift)
    }

    @Test
    fun theModifiersAreHeldTogether() {
        val held = TerminalModifiers().toggled(TerminalKey.CTRL).toggled(TerminalKey.ALT)
        assertEquals(TerminalModifiers(isCtrl = true, isAlt = true), held)
        assertTrue(held.isHeld(TerminalKey.CTRL))
        assertTrue(held.isHeld(TerminalKey.ALT))
        assertFalse(held.isHeld(TerminalKey.SHIFT))
    }

    @Test
    fun aKeyThatIsNoModifierChangesNothingAndNeverShowsPressed() {
        val held = TerminalModifiers(isCtrl = true)
        assertEquals(held, held.toggled(TerminalKey.TAB))
        assertFalse(held.isHeld(TerminalKey.TAB))
    }

    @Test
    fun theXtermParameterAddsOneTwoAndFour() {
        assertEquals(1, TerminalModifiers().xtermParameter)
        assertEquals(2, TerminalModifiers(isShift = true).xtermParameter)
        assertEquals(3, TerminalModifiers(isAlt = true).xtermParameter)
        assertEquals(5, TerminalModifiers(isCtrl = true).xtermParameter)
        assertEquals(8, TerminalModifiers(isCtrl = true, isShift = true, isAlt = true).xtermParameter)
    }
}
