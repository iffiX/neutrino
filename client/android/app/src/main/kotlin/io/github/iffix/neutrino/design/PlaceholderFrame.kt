package io.github.iffix.neutrino.design

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp

/**
 * An empty list: a dashed frame with what is missing, how to fill it, and the button that does.
 *
 * @param line What is missing.
 * @param modifier Placement.
 * @param hint How to fill it.
 * @param action The button that fills it.
 */
@Composable
fun PlaceholderFrame(
    line: String,
    modifier: Modifier = Modifier,
    hint: String? = null,
    action: (@Composable () -> Unit)? = null,
) {
    val palette = NeutrinoTheme.palette
    Column(
        modifier = modifier
            .fillMaxWidth()
            .heightIn(min = 220.dp)
            .drawBehind {
                val stroke = Stroke(
                    width = 1.dp.toPx(),
                    pathEffect = PathEffect.dashPathEffect(floatArrayOf(6.dp.toPx(), 4.dp.toPx())),
                )
                drawRoundRect(palette.borderStrong, cornerRadius = CornerRadius(14.dp.toPx()), style = stroke)
            }
            .padding(horizontal = 16.dp, vertical = 48.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp, Alignment.CenterVertically),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        BasicText(line, style = NeutrinoTheme.body.copy(color = palette.textMuted, textAlign = TextAlign.Center))
        if (hint != null) {
            BasicText(hint, style = NeutrinoTheme.body.copy(color = palette.textFaint, textAlign = TextAlign.Center))
        }
        if (action != null) {
            Column(modifier = Modifier.padding(top = 8.dp)) { action() }
        }
    }
}
