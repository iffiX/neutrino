package io.github.iffix.neutrino.design

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * A translucent round button holding one icon: lit in the accent while what it shows is on, in the
 * danger tone for an action that ends something.
 *
 * @param icon What it shows.
 * @param label What a screen reader names it.
 * @param isActive Whether what it shows is on.
 * @param onPress What a press does.
 * @param modifier Placement.
 * @param isDanger Whether it is drawn in the danger tone.
 * @param isEnabled Whether it takes presses.
 * @param size The circle's diameter.
 */
@Composable
fun RoundButton(
    icon: AppIcon,
    label: String,
    isActive: Boolean,
    onPress: () -> Unit,
    modifier: Modifier = Modifier,
    isDanger: Boolean = false,
    isEnabled: Boolean = true,
    size: Dp = 36.dp,
) {
    val palette = NeutrinoTheme.palette
    val tone = when {
        isDanger -> palette.error
        isActive -> palette.accent
        else -> palette.text
    }
    Box(
        modifier = modifier
            .size(size)
            .alpha(if (isEnabled) 1f else 0.4f)
            .clip(CircleShape)
            .background(palette.surface.copy(alpha = 0.6f))
            .background(if (isActive) palette.accentWash else Color.Transparent)
            .border(1.dp, if (isActive || isDanger) tone else palette.borderStrong.copy(alpha = 0.6f), CircleShape)
            .semantics { contentDescription = label }
            .clickable(enabled = isEnabled, role = Role.Button, onClick = onPress),
        contentAlignment = Alignment.Center,
    ) {
        IconGlyph(icon, tone, size = size / 2)
    }
}
