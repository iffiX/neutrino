package io.github.iffix.neutrino.remotedesktop

import io.github.iffix.neutrino.RDP_SCROLL_STEP_PX
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class RemoteDesktopMouseTest {
    // RustDesk's masks: type in the low three bits (0 move, 1 down, 2 up, 3 wheel), left 8, right 16.
    @Test
    fun aTapMovesThereAndClicksTheLeftButton() {
        assertEquals(
            listOf(RemoteDesktopMouse(5, 6, 0), RemoteDesktopMouse(5, 6, 9), RemoteDesktopMouse(5, 6, 10)),
            RemoteDesktopMouse.tap(5, 6),
        )
    }

    @Test
    fun aLongPressClicksTheRightButton() {
        assertEquals(
            listOf(RemoteDesktopMouse(5, 6, 0), RemoteDesktopMouse(5, 6, 17), RemoteDesktopMouse(5, 6, 18)),
            RemoteDesktopMouse.longPress(5, 6),
        )
    }

    @Test
    fun aDragHoldsTheLeftButtonFromWhereItStartedToWhereItEnded() {
        assertEquals(
            listOf(RemoteDesktopMouse(1, 2, 0), RemoteDesktopMouse(1, 2, 9)),
            RemoteDesktopMouse.dragStart(1, 2),
        )
        assertEquals(RemoteDesktopMouse(3, 4, 0), RemoteDesktopMouse.dragMove(3, 4))
        assertEquals(RemoteDesktopMouse(7, 8, 10), RemoteDesktopMouse.dragEnd(7, 8))
    }

    @Test
    fun underOneStepOfTravelNoWheelEventIsSent() {
        val (event, rest) = RemoteDesktopMouse.wheel(RDP_SCROLL_STEP_PX - 1f)
        assertNull(event)
        assertEquals(RDP_SCROLL_STEP_PX - 1f, rest, 0.0001f)
    }

    @Test
    fun fingersMovingDownTurnTheWheelUpByWholeStepsAndKeepTheRest() {
        val (event, rest) = RemoteDesktopMouse.wheel(RDP_SCROLL_STEP_PX * 2 + 3f)
        assertEquals(RemoteDesktopMouse(0, 2, 3), event)
        assertEquals(3f, rest, 0.0001f)
    }

    @Test
    fun fingersMovingUpTurnTheWheelDown() {
        val (event, rest) = RemoteDesktopMouse.wheel(-RDP_SCROLL_STEP_PX - 1f)
        assertEquals(RemoteDesktopMouse(0, -1, 3), event)
        assertEquals(-1f, rest, 0.0001f)
    }
}
