package io.github.iffix.neutrino.design

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.unit.dp

/**
 * The body of a list screen: a lazy column with the 16 dp gutter, padded above the keyboard.
 *
 * @param modifier Placement.
 * @param content The items: cards made of [cardRows], with [gap] between them.
 */
@Composable
fun ScreenList(modifier: Modifier = Modifier, content: LazyListScope.() -> Unit) {
    LazyColumn(
        modifier = modifier.fillMaxSize().imePadding(),
        contentPadding = PaddingValues(16.dp),
        content = content,
    )
}

/** The 16 dp between two cards of a [ScreenList]. */
fun LazyListScope.gap() {
    item { Spacer(Modifier.height(16.dp)) }
}

/**
 * One card whose rows are items of the list: each row draws its slice of the card.
 *
 * @param rows The card's rows.
 * @param key Each row's key, unique in the list.
 * @param row One row, given whether a divider follows it.
 */
fun <T : Any> LazyListScope.cardRows(
    rows: List<T>,
    key: (T) -> Any,
    row: @Composable ColumnScope.(T, Boolean) -> Unit,
) {
    itemsIndexed(rows, key = { _, item -> key(item) }) { index, item ->
        CardSlice(isFirst = index == 0, isLast = index == rows.lastIndex) { row(item, index < rows.lastIndex) }
    }
}

/**
 * One slice of a card: the card's ground and side borders, with its rounded top on the first
 * slice and its rounded bottom on the last.
 *
 * @param isFirst Whether the slice is the card's top.
 * @param isLast Whether the slice is the card's bottom.
 * @param modifier Placement.
 * @param content The slice's rows.
 */
@Composable
fun CardSlice(
    isFirst: Boolean,
    isLast: Boolean,
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit,
) {
    val palette = NeutrinoTheme.palette
    Column(
        modifier = modifier
            .fillMaxWidth()
            .drawWithContent {
                val radius = 14.dp.toPx()
                val reach = radius * 2
                val top = if (isFirst) 0f else -reach
                val bottom = if (isLast) size.height else size.height + reach
                val stroke = 1.dp.toPx()
                clipRect(0f, 0f, size.width, size.height) {
                    drawRoundRect(
                        palette.surface,
                        topLeft = Offset(0f, top),
                        size = Size(size.width, bottom - top),
                        cornerRadius = CornerRadius(radius),
                    )
                    drawRoundRect(
                        palette.border,
                        topLeft = Offset(stroke / 2, top + stroke / 2),
                        size = Size(size.width - stroke, bottom - top - stroke),
                        cornerRadius = CornerRadius(radius),
                        style = Stroke(stroke),
                    )
                }
                drawContent()
            }
            .padding(horizontal = 16.dp)
            .padding(top = if (isFirst) 4.dp else 0.dp, bottom = if (isLast) 4.dp else 0.dp),
        content = content,
    )
}
