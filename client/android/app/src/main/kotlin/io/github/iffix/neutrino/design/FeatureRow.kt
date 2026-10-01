package io.github.iffix.neutrino.design

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.FlowRowScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp

/**
 * One row of a card: the status dot, the row's lines, and its actions wrapped under the lines,
 * right-aligned, in one order with a red-outlined action last.
 *
 * @param modifier Placement.
 * @param marker The row's status, or null for none.
 * @param onClick What pressing the whole row does, or null when the row is not a button.
 * @param isGreyed Whether the row's lines are dimmed, for something unusable here.
 * @param hasDivider Whether a hairline follows the row.
 * @param hasChevron Whether a chevron ends the row, for a row that opens something.
 * @param actions The row's buttons, or null for none.
 * @param content The row's lines.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun FeatureRow(
    modifier: Modifier = Modifier,
    marker: DotTone? = null,
    onClick: (() -> Unit)? = null,
    isGreyed: Boolean = false,
    hasDivider: Boolean = true,
    hasChevron: Boolean = false,
    actions: (@Composable FlowRowScope.() -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    val palette = NeutrinoTheme.palette
    var shaped = modifier.fillMaxWidth()
    if (hasDivider) {
        shaped = shaped.drawBehind {
            drawLine(palette.border, Offset(0f, size.height), Offset(size.width, size.height), 1.dp.toPx())
        }
    }
    if (onClick != null) shaped = shaped.clickable(role = Role.Button, onClick = onClick)
    Column(modifier = shaped.padding(vertical = 12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.Top) {
            if (marker != null) StatusDot(marker, Modifier.padding(top = 7.dp))
            Column(modifier = Modifier.weight(1f).alpha(if (isGreyed) 0.5f else 1f), content = content)
            if (hasChevron) {
                IconGlyph(AppIcon.CHEVRON_RIGHT, palette.textFaint, Modifier.padding(top = 3.dp), size = 16.dp)
            }
        }
        if (actions != null) {
            FlowRow(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.End),
                verticalArrangement = Arrangement.spacedBy(8.dp),
                itemVerticalAlignment = Alignment.CenterVertically,
                content = actions,
            )
        }
    }
}
