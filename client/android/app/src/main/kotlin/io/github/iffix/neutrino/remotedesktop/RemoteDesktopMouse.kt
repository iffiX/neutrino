package io.github.iffix.neutrino.remotedesktop

import io.github.iffix.neutrino.RDP_MOUSE_DOWN
import io.github.iffix.neutrino.RDP_MOUSE_LEFT
import io.github.iffix.neutrino.RDP_MOUSE_MOVE
import io.github.iffix.neutrino.RDP_MOUSE_RIGHT
import io.github.iffix.neutrino.RDP_MOUSE_UP
import io.github.iffix.neutrino.RDP_MOUSE_WHEEL
import io.github.iffix.neutrino.RDP_SCROLL_STEP_PX

/**
 * One mouse event as RustDesk takes it.
 *
 * @property x The column in the remote picture, or the horizontal wheel steps.
 * @property y The row, or the vertical wheel steps.
 * @property mask The type in the low three bits and the buttons above.
 */
data class RemoteDesktopMouse(val x: Int, val y: Int, val mask: Int) {
    companion object {
        /**
         * A tap: the pointer moves there, then the left button goes down and up.
         *
         * @param x The column.
         * @param y The row.
         * @return The events.
         */
        fun tap(x: Int, y: Int): List<RemoteDesktopMouse> = click(x, y, RDP_MOUSE_LEFT)

        /**
         * A long press: the right button's click there.
         *
         * @param x The column.
         * @param y The row.
         * @return The events.
         */
        fun longPress(x: Int, y: Int): List<RemoteDesktopMouse> = click(x, y, RDP_MOUSE_RIGHT)

        /**
         * The start of a one-finger drag: the left button goes down where the finger landed.
         *
         * @param x The column.
         * @param y The row.
         * @return The events.
         */
        fun dragStart(x: Int, y: Int): List<RemoteDesktopMouse> =
            listOf(RemoteDesktopMouse(x, y, RDP_MOUSE_MOVE), RemoteDesktopMouse(x, y, RDP_MOUSE_DOWN or RDP_MOUSE_LEFT))

        /**
         * The finger moving during a drag.
         *
         * @param x The column.
         * @param y The row.
         * @return The event.
         */
        fun dragMove(x: Int, y: Int): RemoteDesktopMouse = RemoteDesktopMouse(x, y, RDP_MOUSE_MOVE)

        /**
         * The end of a drag: the left button comes up where the finger left.
         *
         * @param x The column.
         * @param y The row.
         * @return The event.
         */
        fun dragEnd(x: Int, y: Int): RemoteDesktopMouse = RemoteDesktopMouse(x, y, RDP_MOUSE_UP or RDP_MOUSE_LEFT)

        /**
         * The wheel steps a two-finger scroll has travelled, and what is left over.
         *
         * @param travel The fingers' downward travel not yet sent, in pixels.
         * @return The wheel event, or null under one step, and the travel still unsent.
         */
        fun wheel(travel: Float): Pair<RemoteDesktopMouse?, Float> {
            val steps = (travel / RDP_SCROLL_STEP_PX).toInt()
            if (steps == 0) return null to travel
            return RemoteDesktopMouse(0, steps, RDP_MOUSE_WHEEL) to travel - steps * RDP_SCROLL_STEP_PX
        }

        private fun click(x: Int, y: Int, button: Int): List<RemoteDesktopMouse> = listOf(
            RemoteDesktopMouse(x, y, RDP_MOUSE_MOVE),
            RemoteDesktopMouse(x, y, RDP_MOUSE_DOWN or button),
            RemoteDesktopMouse(x, y, RDP_MOUSE_UP or button),
        )
    }
}
