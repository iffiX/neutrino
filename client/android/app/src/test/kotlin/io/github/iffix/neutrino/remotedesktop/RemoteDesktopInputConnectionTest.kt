package io.github.iffix.neutrino.remotedesktop

import android.view.KeyEvent
import android.view.View
import org.junit.Assert.assertEquals
import org.junit.Test

class RemoteDesktopInputConnectionTest {
    private val core = FakeRemoteDesktopCore()
    private val sender = RemoteDesktopInputSender(core) {}
    private val connection = RemoteDesktopInputConnection(View(null), sender)

    @Test
    fun committedTextIsSentAsOneText() {
        connection.commitText("你好", 1)
        assertEquals(listOf("text 你好"), core.calls)
    }

    @Test
    fun aCompositionSendsNothingUntilItIsCommitted() {
        connection.setComposingText("n", 1)
        connection.setComposingText("ni", 1)
        connection.setComposingText("nihao", 1)
        assertEquals(emptyList<String>(), core.calls)
        connection.commitText("你好", 1)
        assertEquals(listOf("text 你好"), core.calls)
    }

    @Test
    fun aCompositionLeftUnfinishedSendsNothing() {
        connection.setComposingText("ni", 1)
        connection.finishComposingText()
        assertEquals(emptyList<String>(), core.calls)
    }

    @Test
    fun aDeleteBeforeTheCursorIsBackspaces() {
        connection.deleteSurroundingText(2, 0)
        assertEquals(List(2) { listOf("key VK_BACK down", "key VK_BACK up") }.flatten(), core.calls)
    }

    @Test
    fun aDeleteAfterTheCursorIsDelete() {
        connection.deleteSurroundingText(0, 1)
        assertEquals(listOf("key VK_DELETE down", "key VK_DELETE up"), core.calls)
    }

    @Test
    fun enterIsTheEnterKey() {
        connection.keyDown(KeyEvent.KEYCODE_ENTER, '\n'.code)
        assertEquals(listOf("key VK_RETURN down", "key VK_RETURN up"), core.calls)
    }

    @Test
    fun aCommittedLineBreakIsTheEnterKey() {
        connection.commitText("\n", 1)
        assertEquals(listOf("key VK_RETURN down", "key VK_RETURN up"), core.calls)
    }

    @Test
    fun backspaceTabAndTheArrowsAreTheirKeys() {
        connection.keyDown(KeyEvent.KEYCODE_DEL, 0)
        connection.keyDown(KeyEvent.KEYCODE_TAB, '\t'.code)
        connection.keyDown(KeyEvent.KEYCODE_DPAD_LEFT, 0)
        assertEquals(
            listOf("VK_BACK", "VK_TAB", "VK_LEFT").flatMap { listOf("key $it down", "key $it up") },
            core.calls,
        )
    }

    @Test
    fun aPrintableKeyIsSentAsText() {
        connection.keyDown(KeyEvent.KEYCODE_A, 'a'.code)
        assertEquals(listOf("text a"), core.calls)
    }

    @Test
    fun aKeyThatTypesNothingIsDropped() {
        connection.keyDown(KeyEvent.KEYCODE_VOLUME_UP, 0)
        assertEquals(emptyList<String>(), core.calls)
    }

    @Test
    fun aModifierHeldWithASingleLetterIsThatKey() {
        sender.barKey(RemoteDesktopKey.CTRL)
        connection.commitText("c", 1)
        assertEquals(
            listOf("key VK_CONTROL down", "key VK_C down", "key VK_C up", "key VK_CONTROL up"),
            core.calls,
        )
    }

    @Test
    fun theEditorActionSendsNothing() {
        connection.performEditorAction(0)
        assertEquals(emptyList<String>(), core.calls)
    }
}
