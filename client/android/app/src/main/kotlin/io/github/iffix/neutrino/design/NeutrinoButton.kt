package io.github.iffix.neutrino.design

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * A button in one of the panel's tiers.
 *
 * @param label What it says.
 * @param onClick What a press does.
 * @param modifier Placement.
 * @param tier Its tier.
 * @param icon An icon before the label.
 * @param isEnabled Whether it takes presses; a dead button is dimmed.
 * @param isSmall Whether it is the small size a row carries.
 * @param isCommit Whether it wears the glow of the one action a section commits with.
 * @param isWide Whether it fills the width.
 * @param isDone Whether it shows the green of an action just done, like a copy.
 */
@Composable
fun NeutrinoButton(
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    tier: ButtonTier = ButtonTier.PLAIN,
    icon: AppIcon? = null,
    isEnabled: Boolean = true,
    isSmall: Boolean = false,
    isCommit: Boolean = false,
    isWide: Boolean = false,
    isDone: Boolean = false,
) {
    val palette = NeutrinoTheme.palette
    val shape = RoundedCornerShape(6.dp)
    val (border, background, content) = when {
        isDone -> Triple(palette.ok, palette.elevated, palette.ok)
        tier == ButtonTier.PRIMARY -> Triple(palette.accent, palette.accentWash, palette.accent)
        tier == ButtonTier.DANGER -> Triple(palette.error, Color.Transparent, palette.error)
        tier == ButtonTier.GHOST -> Triple(Color.Transparent, Color.Transparent, palette.textMuted)
        else -> Triple(palette.borderStrong, palette.elevated, palette.text)
    }
    var shaped = modifier
    if (isCommit && isEnabled) {
        shaped = shaped.shadow(10.dp, shape, ambientColor = palette.accent, spotColor = palette.accent)
    }
    if (isWide) shaped = shaped.fillMaxWidth()
    Row(
        modifier = shaped
            .alpha(if (isEnabled) 1f else 0.45f)
            .clip(shape)
            .background(background)
            .border(1.dp, border, shape)
            .clickable(enabled = isEnabled, role = Role.Button, onClick = onClick)
            .padding(horizontal = if (isSmall) 10.dp else 14.dp, vertical = if (isSmall) 4.dp else 7.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.CenterHorizontally),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (icon != null) IconGlyph(icon, content, size = 14.dp)
        BasicText(
            text = label,
            style = NeutrinoTheme.buttonLabel.copy(color = content, fontSize = if (isSmall) 12.sp else 13.sp),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}
