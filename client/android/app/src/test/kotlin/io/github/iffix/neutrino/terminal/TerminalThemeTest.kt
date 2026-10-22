package io.github.iffix.neutrino.terminal

import io.github.iffix.neutrino.design.NeutrinoPalette
import org.junit.Assert.assertEquals
import org.junit.Test

class TerminalThemeTest {
    private val tango = mapOf(
        "black" to "#2e3436",
        "red" to "#cc0000",
        "green" to "#4e9a06",
        "yellow" to "#c4a000",
        "blue" to "#3465a4",
        "magenta" to "#75507b",
        "cyan" to "#06989a",
        "white" to "#d3d7cf",
        "brightBlack" to "#555753",
        "brightRed" to "#ef2929",
        "brightGreen" to "#8ae234",
        "brightYellow" to "#fce94f",
        "brightBlue" to "#729fcf",
        "brightMagenta" to "#ad7fa8",
        "brightCyan" to "#34e2e2",
        "brightWhite" to "#eeeeec",
    )

    @Test
    fun theSixteenAnsiColoursAreTheTangoPaletteInEveryTheme() {
        for (palette in listOf(NeutrinoPalette.dark, NeutrinoPalette.light)) {
            val terminal = TerminalTheme.of(palette).terminal
            assertEquals(tango, terminal.filterKeys { it in tango })
            assertEquals(tango.size + 5, terminal.size)
        }
    }

    @Test
    fun theDarkThemeDrawsLightTextOnTheDarkGround() {
        val terminal = TerminalTheme.of(NeutrinoPalette.dark).terminal
        assertEquals("#070809", terminal["background"])
        assertEquals("#e6edf3", terminal["foreground"])
        assertEquals("#22d3ee", terminal["cursor"])
        assertEquals("#070809", terminal["cursorAccent"])
        assertEquals("#22d3ee40", terminal["selectionBackground"])
    }

    @Test
    fun theLightThemeDrawsDarkTextOnTheLightGround() {
        val terminal = TerminalTheme.of(NeutrinoPalette.light).terminal
        assertEquals("#e8ebf0", terminal["background"])
        assertEquals("#0f172a", terminal["foreground"])
        assertEquals("#0c6a84", terminal["cursor"])
        assertEquals("#e8ebf0", terminal["cursorAccent"])
        assertEquals("#0c6a8440", terminal["selectionBackground"])
    }

    @Test
    fun theMenuAroundTheTerminalsFollowsThePalette() {
        val light = TerminalTheme.of(NeutrinoPalette.light).chrome
        assertEquals("#e8ebf0", light["menu-ground"])
        assertEquals("#0f172a", light["menu-text"])
        val dark = TerminalTheme.of(NeutrinoPalette.dark).chrome
        assertEquals("#070809", dark["menu-ground"])
        assertEquals("#e6edf3", dark["menu-text"])
    }
}
