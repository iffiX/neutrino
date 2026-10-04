package io.github.iffix.neutrino.remotedesktop

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RemoteDesktopButtonTest {
    private val pressed = mutableListOf<String>()

    private val down = RemoteDesktopKeyboard(isShown = false, height = 0)

    private val docked = RemoteDesktopKeyboard(isShown = true, height = 640)

    private val floating = RemoteDesktopKeyboard(isShown = true, height = 0)

    private fun press(
        button: RemoteDesktopButton,
        keyboard: RemoteDesktopKeyboard = down,
        isKeyBarShown: Boolean = false,
    ) = button.press(
        keyboard,
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
        for (button in RemoteDesktopButton.entries) assertFalse(button.isActive(down, false))
    }

    @Test
    fun keyboardIsActiveWhileTheKeyboardCoversThePicture() {
        assertTrue(RemoteDesktopButton.KEYBOARD.isActive(docked, false))
        assertFalse(RemoteDesktopButton.KEYBOARD.isActive(down, true))
    }

    @Test
    fun aFloatingKeyboardReadsAsShown() {
        assertTrue(floating.isShown)
        assertTrue(RemoteDesktopButton.KEYBOARD.isActive(floating, false))
    }

    @Test
    fun keyboardRaisesOrPutsAwayTheKeyboard() {
        press(RemoteDesktopButton.KEYBOARD, down)
        press(RemoteDesktopButton.KEYBOARD, docked)
        assertEquals(listOf("keyboard true", "keyboard false"), pressed)
    }

    @Test
    fun keyboardPutsAwayAFloatingKeyboard() {
        press(RemoteDesktopButton.KEYBOARD, floating)
        assertEquals(listOf("keyboard false"), pressed)
    }

    @Test
    fun keysTogglesTheKeyBar() {
        press(RemoteDesktopButton.KEYS, isKeyBarShown = false)
        press(RemoteDesktopButton.KEYS, isKeyBarShown = true)
        assertEquals(listOf("keys true", "keys false"), pressed)
        assertTrue(RemoteDesktopButton.KEYS.isActive(down, true))
    }

    @Test
    fun closeEndsTheSession() {
        press(RemoteDesktopButton.CLOSE, docked, isKeyBarShown = true)
        assertEquals(listOf("close"), pressed)
        assertFalse(RemoteDesktopButton.CLOSE.isActive(docked, true))
    }
}
