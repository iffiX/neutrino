package io.github.iffix.neutrino.design

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Modifier
import io.github.iffix.neutrino.CLIENT_ARM_MILLIS
import kotlinx.coroutines.delay

/**
 * A destructive button: the first press arms it (its label asks for a second press and its fill
 * turns red), the second within 5 s acts, and a press elsewhere disarms it.
 *
 * @param key What the button acts on, unique in the window.
 * @param label What it says while not armed.
 * @param armedLabel What it says while armed.
 * @param onAct What the second press does.
 * @param modifier Placement.
 * @param isEnabled Whether it takes presses.
 * @param isBusy Whether its job runs: a spinner, and [label] is the in-progress word.
 * @param isSmall Whether it is the small size a row carries.
 */
@Composable
fun ArmedButton(
    key: String,
    label: String,
    armedLabel: String,
    onAct: () -> Unit,
    modifier: Modifier = Modifier,
    isEnabled: Boolean = true,
    isBusy: Boolean = false,
    isSmall: Boolean = true,
) {
    val arm = LocalArm.current
    val isArmed = arm.armed == key && isEnabled && !isBusy
    LaunchedEffect(isArmed) {
        if (isArmed) {
            delay(CLIENT_ARM_MILLIS)
            if (arm.armed == key) arm.armed = null
        }
    }
    NeutrinoButton(
        label = if (isArmed) armedLabel else label,
        onClick = {
            if (isArmed) {
                arm.armed = null
                onAct()
            } else {
                arm.armed = key
            }
        },
        modifier = modifier,
        tier = ButtonTier.DANGER,
        isEnabled = isEnabled && !isBusy,
        isSmall = isSmall,
        isBusy = isBusy,
        isArmed = isArmed,
    )
}
