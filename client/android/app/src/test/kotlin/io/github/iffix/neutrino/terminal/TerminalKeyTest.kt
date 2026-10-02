package io.github.iffix.neutrino.terminal

import org.junit.Assert.assertEquals
import org.junit.Test

class TerminalKeyTest {
    @Test
    fun theRowReadsInTheOrderOfTheStandard() {
        assertEquals(
            listOf("Esc", "Tab", "Ctrl", "Shift", "Alt", "←", "↑", "↓", "→"),
            TerminalKey.entries.map { it.label },
        )
    }

    @Test
    fun onlyCtrlShiftAndAltAreHeld() {
        assertEquals(
            setOf(TerminalKey.CTRL, TerminalKey.SHIFT, TerminalKey.ALT),
            TerminalKey.entries.filter { it.isModifier }.toSet(),
        )
    }

    @Test
    fun aPlainKeySendsItsOwnSequence() {
        val none = TerminalModifiers()
        assertEquals("\u001b", TerminalKey.ESCAPE.sequence(none))
        assertEquals("\t", TerminalKey.TAB.sequence(none))
        assertEquals("\u001b[D", TerminalKey.LEFT.sequence(none))
        assertEquals("\u001b[A", TerminalKey.UP.sequence(none))
        assertEquals("\u001b[B", TerminalKey.DOWN.sequence(none))
        assertEquals("\u001b[C", TerminalKey.RIGHT.sequence(none))
    }

    @Test
    fun shiftTurnsTabIntoBackTab() {
        assertEquals("\u001b[Z", TerminalKey.TAB.sequence(TerminalModifiers(isShift = true)))
    }

    @Test
    fun altPutsEscapeBeforeEscAndTab() {
        val alt = TerminalModifiers(isAlt = true)
        assertEquals("\u001b\u001b", TerminalKey.ESCAPE.sequence(alt))
        assertEquals("\u001b\t", TerminalKey.TAB.sequence(alt))
    }

    @Test
    fun anArrowCarriesEveryModifierInItsParameter() {
        assertEquals("\u001b[1;2A", TerminalKey.UP.sequence(TerminalModifiers(isShift = true)))
        assertEquals("\u001b[1;3D", TerminalKey.LEFT.sequence(TerminalModifiers(isAlt = true)))
        assertEquals("\u001b[1;5C", TerminalKey.RIGHT.sequence(TerminalModifiers(isCtrl = true)))
        assertEquals(
            "\u001b[1;8B",
            TerminalKey.DOWN.sequence(TerminalModifiers(isCtrl = true, isShift = true, isAlt = true)),
        )
    }

    @Test
    fun aModifierSendsNothing() {
        for (key in TerminalKey.entries.filter { it.isModifier }) {
            assertEquals("", key.sequence(TerminalModifiers(isCtrl = true)))
        }
    }
}
