package io.github.iffix.neutrino.shell

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import io.github.iffix.neutrino.design.IconGlyph
import io.github.iffix.neutrino.design.NeutrinoTheme

/**
 * The portrait navigation: one icon per tab along the bottom, the open one lit.
 *
 * @param current The tab the open screen belongs to.
 * @param onOpen What pressing a tab does.
 * @param modifier Placement.
 */
@Composable
fun BottomBar(current: AppScreen, onOpen: (AppScreen) -> Unit, modifier: Modifier = Modifier) {
    val palette = NeutrinoTheme.palette
    val words = NeutrinoTheme.words
    Row(
        modifier = modifier
            .fillMaxWidth()
            .background(palette.bg)
            .drawBehind { drawLine(palette.border, Offset.Zero, Offset(size.width, 0f), 1.dp.toPx()) }
            .navigationBarsPadding()
            .height(56.dp),
    ) {
        for (tab in AppScreen.tabs) {
            val isActive = tab == current
            val title = words.word(tab.titleKey)
            Box(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxHeight()
                    .background(if (isActive) palette.accentWash else palette.bg)
                    .drawBehind {
                        if (isActive) {
                            val width = 22.dp.toPx()
                            drawRoundRect(
                                palette.accent,
                                topLeft = Offset((size.width - width) / 2, 0f),
                                size = Size(width, 2.dp.toPx()),
                                cornerRadius = CornerRadius(1.dp.toPx()),
                            )
                        }
                    }
                    .semantics {
                        contentDescription = title
                        selected = isActive
                    }
                    .clickable(role = Role.Tab) { onOpen(tab) },
                contentAlignment = Alignment.Center,
            ) {
                val icon = tab.icon ?: return@Box
                IconGlyph(icon, if (isActive) palette.accent else palette.textMuted, size = 18.dp)
            }
        }
    }
}
