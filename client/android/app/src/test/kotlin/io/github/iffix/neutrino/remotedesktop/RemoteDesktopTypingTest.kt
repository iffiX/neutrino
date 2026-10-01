package io.github.iffix.neutrino.remotedesktop

import org.junit.Assert.assertEquals
import org.junit.Test

class RemoteDesktopTypingTest {
    @Test
    fun aComposedWordSendsOnlyItsNewLetter() {
        assertEquals(RemoteDesktopTyping(0, "l"), RemoteDesktopTyping.between(" hel", " hell"))
    }

    @Test
    fun aDeletionSendsOneBackspacePerCharacter() {
        assertEquals(RemoteDesktopTyping(1, ""), RemoteDesktopTyping.between(" hellox", " hello"))
        assertEquals(RemoteDesktopTyping(1, ""), RemoteDesktopTyping.between(" ", ""))
    }

    @Test
    fun aReplacedWordDeletesItsEndAndTypesTheNewOne() {
        assertEquals(RemoteDesktopTyping(1, "llo"), RemoteDesktopTyping.between(" hey", " hello"))
    }

    @Test
    fun theSameContentSendsNothing() {
        assertEquals(RemoteDesktopTyping(0, ""), RemoteDesktopTyping.between(" a", " a"))
    }
}
