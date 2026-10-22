package io.github.iffix.neutrino.terminal

import io.github.iffix.neutrino.design.AppIcon
import io.github.iffix.neutrino.remotedesktop.RemoteDesktopButton
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TerminalControlTest {
    private val pressed = mutableListOf<String>()

    private fun press(control: TerminalControl, isKeyboardShown: Boolean, isKeyRowShown: Boolean) = control.press(
        isKeyboardShown,
        isKeyRowShown,
        onKeyboard = { pressed += "keyboard $it" },
        onKeyRow = { pressed += "keys $it" },
    )

    @Test
    fun theButtonsAreKeyboardThenKeysWithTheViewersIconsAndWords() {
        assertEquals(listOf(TerminalControl.KEYBOARD, TerminalControl.KEYS), TerminalControl.entries)
        assertEquals(AppIcon.KEYBOARD, TerminalControl.KEYBOARD.icon)
        assertEquals(RemoteDesktopButton.KEYBOARD.icon, TerminalControl.KEYBOARD.icon)
        assertEquals(RemoteDesktopButton.KEYS.icon, TerminalControl.KEYS.icon)
        assertEquals(RemoteDesktopButton.KEYBOARD.wordKey, TerminalControl.KEYBOARD.wordKey)
        assertEquals(RemoteDesktopButton.KEYS.wordKey, TerminalControl.KEYS.wordKey)
    }

    @Test
    fun keyboardShowsTheKeyboardsStateAndKeysTheKeyRows() {
        assertTrue(TerminalControl.KEYBOARD.isActive(isKeyboardShown = true, isKeyRowShown = false))
        assertFalse(TerminalControl.KEYBOARD.isActive(isKeyboardShown = false, isKeyRowShown = true))
        assertTrue(TerminalControl.KEYS.isActive(isKeyboardShown = false, isKeyRowShown = true))
        assertFalse(TerminalControl.KEYS.isActive(isKeyboardShown = true, isKeyRowShown = false))
    }

    @Test
    fun keyboardRaisesOrPutsAwayTheKeyboard() {
        press(TerminalControl.KEYBOARD, isKeyboardShown = false, isKeyRowShown = true)
        press(TerminalControl.KEYBOARD, isKeyboardShown = true, isKeyRowShown = true)
        assertEquals(listOf("keyboard true", "keyboard false"), pressed)
    }

    @Test
    fun keysHidesAShownKeyRowAndShowsAHiddenOne() {
        press(TerminalControl.KEYS, isKeyboardShown = false, isKeyRowShown = true)
        press(TerminalControl.KEYS, isKeyboardShown = true, isKeyRowShown = false)
        assertEquals(listOf("keys false", "keys true"), pressed)
    }
}
