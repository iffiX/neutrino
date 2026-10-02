package io.github.iffix.neutrino.design

import androidx.compose.animation.core.animateDpAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp

/**
 * The panel's toggle switch a size down: a label and a track whose thumb slides on. A disabled
 * switch has no accent: the track's border and the thumb in the faint text colour, the label muted.
 *
 * @param label What it switches.
 * @param isOn Whether it is on.
 * @param onChange What switching does, with the new state.
 * @param modifier Placement.
 * @param isEnabled Whether it takes presses.
 */
@Composable
fun ToggleSwitch(
    label: String,
    isOn: Boolean,
    onChange: (Boolean) -> Unit,
    modifier: Modifier = Modifier,
    isEnabled: Boolean = true,
) {
    val palette = NeutrinoTheme.palette
    val offset by animateDpAsState(if (isOn) 14.dp else 0.dp, label = "thumb")
    val isAccented = isOn && isEnabled
    val labelColor = if (isEnabled) palette.text else palette.textMuted
    val edge = when {
        !isEnabled -> palette.textFaint
        isOn -> palette.accent
        else -> palette.borderStrong
    }
    Row(
        modifier = modifier
            .toggleable(value = isOn, enabled = isEnabled, role = Role.Switch, onValueChange = onChange)
            .padding(2.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        BasicText(label, style = NeutrinoTheme.fieldLabel.copy(color = labelColor))
        Box(
            modifier = Modifier
                .size(width = 32.dp, height = 18.dp)
                .clip(RoundedCornerShape(50))
                .background(if (isAccented) palette.accentWash else palette.bg)
                .border(1.dp, edge, RoundedCornerShape(50)),
            contentAlignment = Alignment.CenterStart,
        ) {
            Box(
                modifier = Modifier
                    .offset { IntOffset((3.dp + offset).roundToPx(), 0) }
                    .size(10.dp)
                    .clip(CircleShape)
                    .background(if (isAccented) palette.accent else palette.textFaint),
            )
        }
    }
}
