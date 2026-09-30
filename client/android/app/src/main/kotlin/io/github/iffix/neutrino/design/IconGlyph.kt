package io.github.iffix.neutrino.design

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.graphics.vector.PathParser
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import io.github.iffix.neutrino.ICON_STROKE_WIDTH
import io.github.iffix.neutrino.ICON_VIEWBOX

/**
 * One icon of the set, stroked at 1.6 units of its 24-unit box.
 *
 * @param icon Which icon.
 * @param color The stroke colour.
 * @param modifier Placement.
 * @param size The edge of the square it fills.
 */
@Composable
fun IconGlyph(icon: AppIcon, color: Color, modifier: Modifier = Modifier, size: Dp = 18.dp) {
    val paths = remember(icon) { icon.paths.map { PathParser().parsePathString(it).toPath() } }
    Canvas(modifier = modifier.size(size)) {
        val ratio = this.size.minDimension / ICON_VIEWBOX
        scale(ratio, pivot = Offset.Zero) {
            for (path in paths) {
                drawPath(
                    path = path,
                    color = color,
                    style = Stroke(width = ICON_STROKE_WIDTH, cap = StrokeCap.Round, join = StrokeJoin.Round),
                )
            }
        }
    }
}
