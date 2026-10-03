package io.github.iffix.neutrino.remotedesktop

import org.junit.Assert.assertEquals
import org.junit.Test

class RemoteDesktopInputSenderTest {
    private val core = FakeRemoteDesktopCore()
    private val reported = mutableListOf<Set<RemoteDesktopKey>>()
    private val sender = RemoteDesktopInputSender(core) { reported += it }

    @Test
    fun aModifierIsHeldUntilTheNextKey() {
        sender.barKey(RemoteDesktopKey.ALT)
        assertEquals(setOf(RemoteDesktopKey.ALT), sender.held)
        sender.barKey(RemoteDesktopKey.TAB)
        assertEquals(
            listOf("key VK_MENU down", "key VK_TAB down", "key VK_TAB up", "key VK_MENU up"),
            core.calls,
        )
        assertEquals(listOf(setOf(RemoteDesktopKey.ALT), emptySet()), reported)
    }

    @Test
    fun aSecondPressLetsAModifierGo() {
        sender.barKey(RemoteDesktopKey.SHIFT)
        sender.barKey(RemoteDesktopKey.SHIFT)
        assertEquals(listOf("key VK_SHIFT down", "key VK_SHIFT up"), core.calls)
        assertEquals(emptySet<RemoteDesktopKey>(), sender.held)
    }

    @Test
    fun textWithAModifierHeldIsSentAsTextAndLetsItGo() {
        sender.barKey(RemoteDesktopKey.CTRL)
        sender.type("你好")
        assertEquals(listOf("key VK_CONTROL down", "text 你好", "key VK_CONTROL up"), core.calls)
    }

    @Test
    fun pasteSendsTheClipboardThenCtrlV() {
        sender.paste("copied")
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
    fun anEmptyPasteSendsNothing() {
        sender.paste("")
        assertEquals(emptyList<String>(), core.calls)
    }
}
