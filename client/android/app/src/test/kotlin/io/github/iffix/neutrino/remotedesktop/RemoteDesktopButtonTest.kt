package io.github.iffix.neutrino.remotedesktop

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RemoteDesktopButtonTest {
    private val pressed = mutableListOf<String>()

    private fun press(button: RemoteDesktopButton, keyboardHeight: Int = 0, isKeyBarShown: Boolean = false) =
        button.press(
            keyboardHeight,
            isKeyBarShown,
            onKeyboard = { pressed += "keyboard $it" },
            onKeyBar = { pressed += "keys $it" },
            onClose = { pressed += "close" },
        )

    @Test
    fun theButtonsReadKeyboardKeysClose() {
        assertEquals(
            listOf(RemoteDesktopButton.KEYBOARD, RemoteDesktopButton.KEYS, RemoteDesktopButton.CLOSE),
            RemoteDesktopButton.entries,
        )
        assertEquals(listOf(RemoteDesktopButton.CLOSE), RemoteDesktopButton.entries.filter { it.isDanger })
    }

    @Test
    fun noneIsActiveAtTheStart() {
        for (button in RemoteDesktopButton.entries) assertFalse(button.isActive(0, false))
    }

    @Test
    fun keyboardIsActiveWhileTheKeyboardCoversThePicture() {
        assertTrue(RemoteDesktopButton.KEYBOARD.isActive(640, false))
        assertFalse(RemoteDesktopButton.KEYBOARD.isActive(0, true))
    }

    @Test
    fun keyboardRaisesOrPutsAwayTheKeyboard() {
        press(RemoteDesktopButton.KEYBOARD, keyboardHeight = 0)
        press(RemoteDesktopButton.KEYBOARD, keyboardHeight = 640)
        assertEquals(listOf("keyboard true", "keyboard false"), pressed)
    }

    @Test
    fun keysTogglesTheKeyBar() {
        press(RemoteDesktopButton.KEYS, isKeyBarShown = false)
        press(RemoteDesktopButton.KEYS, isKeyBarShown = true)
        assertEquals(listOf("keys true", "keys false"), pressed)
        assertTrue(RemoteDesktopButton.KEYS.isActive(0, true))
    }

    @Test
    fun closeEndsTheSession() {
        press(RemoteDesktopButton.CLOSE, keyboardHeight = 640, isKeyBarShown = true)
        assertEquals(listOf("close"), pressed)
        assertFalse(RemoteDesktopButton.CLOSE.isActive(640, true))
    }
}
