package io.github.iffix.neutrino.design

import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

/**
 * One word of state in a pill, never pressed.
 *
 * @param text The word.
 * @param modifier Placement.
 * @param icon An icon before the word.
 */
@Composable
fun Badge(text: String, modifier: Modifier = Modifier, icon: AppIcon? = null) {
    val palette = NeutrinoTheme.palette
    Row(
        modifier = modifier
            .border(1.dp, palette.borderStrong, RoundedCornerShape(50))
            .padding(horizontal = 8.dp, vertical = 1.dp),
        horizontalArrangement = Arrangement.spacedBy(4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (icon != null) IconGlyph(icon, palette.textMuted, size = 11.dp)
        BasicText(text, style = NeutrinoTheme.badge)
    }
}
