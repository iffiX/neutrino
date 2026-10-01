package io.github.iffix.neutrino.design

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * A row's status marker: a dot in its tone, pulsing while something runs, or the amber spinner
 * a button shows while its job runs.
 *
 * @param tone The tone.
 * @param modifier Placement.
 * @param size The spinner's edge.
 */
@Composable
fun StatusDot(tone: DotTone, modifier: Modifier = Modifier, size: Dp = 10.dp) {
    val palette = NeutrinoTheme.palette
    when (tone) {
        DotTone.SPIN -> {
            val turn by rememberInfiniteTransition(label = "spin").animateFloat(
                initialValue = 0f,
                targetValue = 360f,
                animationSpec = infiniteRepeatable(tween(900, easing = LinearEasing), RepeatMode.Restart),
                label = "turn",
            )
            Canvas(modifier = modifier.size(size)) {
                val stroke = Stroke(width = 2.dp.toPx())
                val arcSize = Size(this.size.width - stroke.width, this.size.height - stroke.width)
                val topLeft = Offset(stroke.width / 2, stroke.width / 2)
                drawArc(palette.border, 0f, 360f, false, topLeft, arcSize, style = stroke)
                drawArc(palette.signalWarn, turn, 90f, false, topLeft, arcSize, style = stroke)
            }
        }

        DotTone.PULSE -> {
            val glow by rememberInfiniteTransition(label = "pulse").animateFloat(
                initialValue = 1f,
                targetValue = 0.3f,
                animationSpec = infiniteRepeatable(tween(800, easing = LinearEasing), RepeatMode.Reverse),
                label = "alpha",
            )
            Canvas(modifier = modifier.size(8.dp)) { drawCircle(palette.signalWarn.copy(alpha = glow)) }
        }

        else -> {
            val color = when (tone) {
                DotTone.OK -> palette.signalOk
                DotTone.WAIT -> palette.signalWarn
                DotTone.BAD -> palette.signalError
                else -> palette.textMuted
            }
            Canvas(modifier = modifier.size(8.dp)) { drawCircle(color) }
        }
    }
}
