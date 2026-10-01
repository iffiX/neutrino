package io.github.iffix.neutrino.remotedesktop

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class RemoteDesktopKeyTest {
    @Test
    fun aLetterOrADigitNamesItsKey() {
        assertEquals("VK_C", RemoteDesktopKey.codeOf('c'))
        assertEquals("VK_C", RemoteDesktopKey.codeOf('C'))
        assertEquals("VK_7", RemoteDesktopKey.codeOf('7'))
    }

    @Test
    fun anyOtherCharacterNamesNoKey() {
        assertNull(RemoteDesktopKey.codeOf('-'))
        assertNull(RemoteDesktopKey.codeOf('é'))
    }

    @Test
    fun onlyCtrlAndAltAreHeld() {
        assertEquals(
            setOf(RemoteDesktopKey.CTRL, RemoteDesktopKey.ALT),
            RemoteDesktopKey.entries.filter { it.isModifier }.toSet(),
        )
    }

    @Test
    fun everyNameIsOneRustDeskKnows() {
        val names = RemoteDesktopKey.entries.map { it.code } + RemoteDesktopKey.ENTER + RemoteDesktopKey.BACKSPACE
        for (name in names) assertTrue(name, name in RUSTDESK_KEY_NAMES)
    }

    private companion object {
        // From KEY_MAP in RustDesk 1.4.9's src/client.rs.
        val RUSTDESK_KEY_NAMES = setOf(
            "VK_ESCAPE",
            "VK_TAB",
            "VK_CONTROL",
            "VK_MENU",
            "VK_LEFT",
            "VK_UP",
            "VK_DOWN",
            "VK_RIGHT",
            "VK_RETURN",
            "VK_BACK",
        )
    }
}
