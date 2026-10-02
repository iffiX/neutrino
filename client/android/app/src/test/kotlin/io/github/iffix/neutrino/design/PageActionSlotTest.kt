package io.github.iffix.neutrino.design

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class PageActionSlotTest {
    private val newTerminal = PageAction("New terminal", AppIcon.TERMINAL, isEnabled = true) {}
    private val scan = PageAction("Scan", AppIcon.CAMERA, isEnabled = false) {}

    @Test
    fun theOfferedActionIsTheHeaders() {
        val slot = PageActionSlot(isHeader = true)
        val page = Any()
        slot.offer(page, newTerminal)
        assertEquals(newTerminal, slot.action)
        slot.withdraw(page)
        assertNull(slot.action)
    }

    @Test
    fun aClosingPageLeavesTheNextPagesAction() {
        val slot = PageActionSlot(isHeader = true)
        val closing = Any()
        val opening = Any()
        slot.offer(closing, newTerminal)
        slot.offer(opening, scan)
        slot.withdraw(closing)
        assertEquals(scan, slot.action)
    }
}
