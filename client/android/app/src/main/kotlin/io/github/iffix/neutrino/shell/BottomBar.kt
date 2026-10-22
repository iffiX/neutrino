package io.github.iffix.neutrino.shell

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.text.BasicText
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
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import io.github.iffix.neutrino.CLIENT_BOTTOM_BAR_HEIGHT_DP
import io.github.iffix.neutrino.design.IconGlyph
import io.github.iffix.neutrino.design.NeutrinoTheme

/**
 * The portrait navigation: one icon per tab along the bottom with its label under it, the open
 * one lit.
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
            .height(CLIENT_BOTTOM_BAR_HEIGHT_DP.dp),
    ) {
        for (tab in AppScreen.tabs) {
            val isActive = tab == current
            val title = words.word(tab.barKey)
            val tone = if (isActive) palette.accent else palette.textMuted
            Column(
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
                verticalArrangement = Arrangement.spacedBy(3.dp, Alignment.CenterVertically),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                tab.icon?.let { IconGlyph(it, tone, size = 18.dp) }
                BasicText(
                    title,
                    style = NeutrinoTheme.badge.copy(
                        color = tone,
                        fontFamily = FontFamily.SansSerif,
                        fontWeight = FontWeight.Medium,
                        textAlign = TextAlign.Center,
                    ),
                    maxLines = 1,
                    softWrap = false,
                )
            }
        }
    }
}
