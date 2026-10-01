package io.github.iffix.neutrino.design

import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput

/** The window's one armed destructive button, which acts on its second press within 5 s. */
class ArmState {
    /** The key of the armed button, or null while none is. */
    var armed: String? by mutableStateOf(null)
}

/** The arming of the window the composition draws. */
val LocalArm = staticCompositionLocalOf { ArmState() }

/**
 * Disarm the armed button when a press lands anywhere but on it.
 *
 * @param arm The window's arming.
 * @return The modifier.
 */
fun Modifier.disarmOnPress(arm: ArmState): Modifier = pointerInput(arm) {
    awaitEachGesture {
        awaitFirstDown(requireUnconsumed = false, pass = PointerEventPass.Initial)
        val armedAtDown = arm.armed
        do {
            val event = awaitPointerEvent(PointerEventPass.Final)
        } while (event.changes.any { it.pressed })
        if (armedAtDown != null && arm.armed == armedAtDown) arm.armed = null
    }
}
