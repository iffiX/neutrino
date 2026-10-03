package io.github.iffix.neutrino.remotedesktop

import android.view.KeyEvent
import android.view.View
import io.github.iffix.neutrino.RDP_TYPE_PACE_MILLIS
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class RemoteDesktopInputConnectionTest {
    private val core = FakeRemoteDesktopCore()
    private lateinit var sender: RemoteDesktopInputSender
    private lateinit var connection: RemoteDesktopInputConnection

    private fun inputTest(body: suspend TestScope.() -> Unit) = runTest {
        sender = RemoteDesktopInputSender(core, backgroundScope) {}
        connection = RemoteDesktopInputConnection(View(null), sender)
        body()
    }

    private fun TestScope.sent(): List<String> {
        advanceTimeBy(RDP_TYPE_PACE_MILLIS * 10)
        runCurrent()
        return core.calls
    }

    @Test
    fun committedTextIsSentOneCharacterAtATime() = inputTest {
        connection.commitText("你好", 1)
        assertEquals(listOf("text 你", "text 好"), sent())
    }

    @Test
    fun aCompositionSendsNothingUntilItIsCommitted() = inputTest {
        connection.setComposingText("n", 1)
        connection.setComposingText("ni", 1)
        connection.setComposingText("nihao", 1)
        assertEquals(emptyList<String>(), sent())
        connection.commitText("你好", 1)
        assertEquals(listOf("text 你", "text 好"), sent())
    }

    @Test
    fun aFinishedCompositionSendsTheWordOnce() = inputTest {
        connection.setComposingText("he", 1)
        connection.setComposingText("hello", 1)
        assertEquals(emptyList<String>(), sent())
        connection.finishComposingText()
        connection.finishComposingText()
        assertEquals("hello".map { "text $it" }, sent())
    }

    @Test
    fun aCompositionReplacedByACommitIsNotSentAgainOnFinish() = inputTest {
        connection.setComposingText("nihao", 1)
        connection.commitText("你好", 1)
        connection.finishComposingText()
        assertEquals(listOf("text 你", "text 好"), sent())
    }

    @Test
    fun aDeleteBeforeTheCursorIsBackspaces() = inputTest {
        connection.deleteSurroundingText(2, 0)
        assertEquals(List(2) { listOf("key VK_BACK down", "key VK_BACK up") }.flatten(), sent())
    }

    @Test
    fun aDeleteAfterTheCursorIsDelete() = inputTest {
        connection.deleteSurroundingText(0, 1)
        assertEquals(listOf("key VK_DELETE down", "key VK_DELETE up"), sent())
    }

    @Test
    fun enterIsTheEnterKey() = inputTest {
        connection.keyDown(KeyEvent.KEYCODE_ENTER, '\n'.code)
        assertEquals(listOf("key VK_RETURN down", "key VK_RETURN up"), sent())
    }

    @Test
    fun aCommittedLineBreakIsTheEnterKey() = inputTest {
        connection.commitText("\n", 1)
        assertEquals(listOf("key VK_RETURN down", "key VK_RETURN up"), sent())
    }

    @Test
    fun backspaceTabAndTheArrowsAreTheirKeys() = inputTest {
        connection.keyDown(KeyEvent.KEYCODE_DEL, 0)
        connection.keyDown(KeyEvent.KEYCODE_TAB, '\t'.code)
        connection.keyDown(KeyEvent.KEYCODE_DPAD_LEFT, 0)
        assertEquals(
            listOf("VK_BACK", "VK_TAB", "VK_LEFT").flatMap { listOf("key $it down", "key $it up") },
            sent(),
        )
    }

    @Test
    fun aPrintableKeyIsSentAsText() = inputTest {
        connection.keyDown(KeyEvent.KEYCODE_A, 'a'.code)
        assertEquals(listOf("text a"), sent())
    }

    @Test
    fun aKeyThatTypesNothingIsDropped() = inputTest {
        connection.keyDown(KeyEvent.KEYCODE_VOLUME_UP, 0)
        assertEquals(emptyList<String>(), sent())
    }

    @Test
    fun aModifierHeldWithASingleLetterIsThatKey() = inputTest {
        sender.barKey(RemoteDesktopKey.CTRL)
        connection.commitText("c", 1)
        assertEquals(
            listOf("key VK_CONTROL down", "key VK_C down", "key VK_C up", "key VK_CONTROL up"),
            sent(),
        )
    }

    @Test
    fun anEditorActionIsTheEnterKey() = inputTest {
        connection.performEditorAction(0)
        assertEquals(listOf("key VK_RETURN down", "key VK_RETURN up"), sent())
    }
}
