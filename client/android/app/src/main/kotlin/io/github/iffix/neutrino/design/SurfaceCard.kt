package io.github.iffix.neutrino.design

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp

/**
 * The unit of one concern: a rounded surface with a hairline border, lit amber while it holds
 * something unsaved.
 *
 * @param modifier Placement.
 * @param isDirty Whether the frame holds an unsaved change.
 * @param content The rows.
 */
@Composable
fun SurfaceCard(modifier: Modifier = Modifier, isDirty: Boolean = false, content: @Composable ColumnScope.() -> Unit) {
    val palette = NeutrinoTheme.palette
    val shape = RoundedCornerShape(14.dp)
    Column(
        modifier = modifier
            .fillMaxWidth()
            .clip(shape)
            .background(palette.surface)
            .border(1.dp, if (isDirty) palette.warn else palette.border, shape)
            .padding(horizontal = 16.dp, vertical = 4.dp),
        content = content,
    )
}
