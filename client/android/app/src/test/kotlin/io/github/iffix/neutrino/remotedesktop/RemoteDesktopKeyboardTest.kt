package io.github.iffix.neutrino.remotedesktop

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RemoteDesktopKeyboardTest {
    @Test
    fun aFloatingKeyboardKeepsTheFocus() {
        assertTrue(RemoteDesktopKeyboard(isShown = true, height = 0).isFocusKept)
    }

    @Test
    fun aDockedKeyboardKeepsTheFocus() {
        assertTrue(RemoteDesktopKeyboard(isShown = true, height = 640).isFocusKept)
    }

    @Test
    fun aKeyboardPutAwayGivesTheFocusUp() {
        assertFalse(RemoteDesktopKeyboard(isShown = false, height = 0).isFocusKept)
    }
}
