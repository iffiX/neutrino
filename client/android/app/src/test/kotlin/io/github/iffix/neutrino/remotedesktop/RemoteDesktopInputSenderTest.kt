package io.github.iffix.neutrino.remotedesktop

import io.github.iffix.neutrino.RDP_TYPE_PACE_MILLIS
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.currentTime
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class RemoteDesktopInputSenderTest {
    private val core = FakeRemoteDesktopCore()
    private val reported = mutableListOf<Set<RemoteDesktopKey>>()

    private fun TestScope.sender() = RemoteDesktopInputSender(core, backgroundScope) { reported += it }

    private fun TestScope.drain() {
        advanceTimeBy(RDP_TYPE_PACE_MILLIS * 10)
        runCurrent()
    }

    @Test
    fun aModifierIsHeldUntilTheNextKey() = runTest {
        val sender = sender()
        sender.barKey(RemoteDesktopKey.ALT)
        runCurrent()
        assertEquals(setOf(RemoteDesktopKey.ALT), sender.held)
        sender.barKey(RemoteDesktopKey.TAB)
        runCurrent()
        assertEquals(
            listOf("key VK_MENU down", "key VK_TAB down", "key VK_TAB up", "key VK_MENU up"),
            core.calls,
        )
        assertEquals(listOf(setOf(RemoteDesktopKey.ALT), emptySet()), reported)
    }

    @Test
    fun aSecondPressLetsAModifierGo() = runTest {
        val sender = sender()
        sender.barKey(RemoteDesktopKey.SHIFT)
        sender.barKey(RemoteDesktopKey.SHIFT)
        runCurrent()
        assertEquals(listOf("key VK_SHIFT down", "key VK_SHIFT up"), core.calls)
        assertEquals(emptySet<RemoteDesktopKey>(), sender.held)
    }

    @Test
    fun textIsTypedOneCharacterAtATimePacedApart() = runTest {
        val sender = sender()
        sender.type("不用")
        runCurrent()
        assertEquals(listOf("text 不"), core.calls)
        advanceTimeBy(RDP_TYPE_PACE_MILLIS - 1)
        runCurrent()
        assertEquals(listOf("text 不"), core.calls)
        advanceTimeBy(1)
        runCurrent()
        assertEquals(listOf("text 不", "text 用"), core.calls)
        assertEquals(RDP_TYPE_PACE_MILLIS, currentTime)
    }

    @Test
    fun aSurrogatePairIsTypedAsOneCharacter() = runTest {
        sender().type("a😀b")
        drain()
        assertEquals(listOf("text a", "text 😀", "text b"), core.calls)
    }

    @Test
    fun aBackspaceAfterAWordWaitsForTheWord() = runTest {
        val sender = sender()
        sender.type("下载")
        sender.press(RemoteDesktopKey.BACKSPACE)
        drain()
        assertEquals(
            listOf("text 下", "text 载", "key VK_BACK down", "key VK_BACK up"),
            core.calls,
        )
    }

    @Test
    fun aModifierHeldWithOneLetterIsThatKey() = runTest {
        val sender = sender()
        sender.barKey(RemoteDesktopKey.CTRL)
        sender.type("c")
        runCurrent()
        assertEquals(
            listOf("key VK_CONTROL down", "key VK_C down", "key VK_C up", "key VK_CONTROL up"),
            core.calls,
        )
    }

    @Test
    fun aLineBreakIsEnter() = runTest {
        sender().type("\n")
        runCurrent()
        assertEquals(listOf("key VK_RETURN down", "key VK_RETURN up"), core.calls)
    }

    @Test
    fun textWithAModifierHeldIsTypedAndLetsItGo() = runTest {
        val sender = sender()
        sender.barKey(RemoteDesktopKey.CTRL)
        sender.type("你好")
        drain()
        assertEquals(
            listOf("key VK_CONTROL down", "text 你", "text 好", "key VK_CONTROL up"),
            core.calls,
        )
    }

    @Test
    fun pasteSendsTheClipboardThenCtrlV() = runTest {
        sender().paste("copied")
        runCurrent()
        assertEquals(
            listOf(
                "clipboard copied",
                "key VK_CONTROL down",
                "key VK_V down",
                "key VK_V up",
                "key VK_CONTROL up",
            ),
            core.calls,
        )
    }

    @Test
    fun anEmptyPasteSendsNothing() = runTest {
        sender().paste("")
        runCurrent()
        assertEquals(emptyList<String>(), core.calls)
    }

    @Test
    fun aClosedSenderSendsNothingMore() = runTest {
        val sender = sender()
        sender.close()
        sender.type("a")
        runCurrent()
        assertEquals(emptyList<String>(), core.calls)
    }
}
