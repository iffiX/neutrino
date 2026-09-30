package io.github.iffix.neutrino.shell

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.iffix.neutrino.design.IconGlyph
import io.github.iffix.neutrino.design.NeutrinoTheme

/**
 * The landscape navigation, after the desktop client's window: the brand, one labelled tab per
 * screen with Settings apart, and this phone's identity at the foot.
 *
 * @param current The tab the open screen belongs to.
 * @param onOpen What pressing a tab does.
 * @param identity This phone's name, platform and version.
 * @param modifier Placement.
 */
@Composable
fun SideBar(current: AppScreen, onOpen: (AppScreen) -> Unit, identity: String, modifier: Modifier = Modifier) {
    val palette = NeutrinoTheme.palette
    val words = NeutrinoTheme.words
    Column(
        modifier = modifier
            .width(196.dp)
            .fillMaxHeight()
            .background(Brush.verticalGradient(listOf(palette.surface, palette.bg)))
            .drawBehind {
                drawLine(palette.border, Offset(size.width, 0f), Offset(size.width, size.height), 1.dp.toPx())
            },
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(57.dp)
                .drawBehind {
                    drawLine(palette.border, Offset(0f, size.height), Offset(size.width, size.height), 1.dp.toPx())
                }
                .padding(horizontal = 18.dp),
            contentAlignment = Alignment.CenterStart,
        ) {
            BasicText(
                words.word("ui.window.title"),
                style = NeutrinoTheme.body.copy(fontWeight = FontWeight.SemiBold, letterSpacing = 0.3.sp),
            )
        }
        Column(
            modifier = Modifier
                .weight(1f)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 10.dp, vertical = 14.dp),
            verticalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            for (tab in AppScreen.tabs) {
                if (tab == AppScreen.SETTINGS) {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 14.dp)
                            .height(1.dp)
                            .background(palette.border),
                    )
                }
                SideTab(tab, isActive = tab == current, onOpen = onOpen)
            }
        }
        BasicText(
            identity,
            style = NeutrinoTheme.mono,
            modifier = Modifier
                .fillMaxWidth()
                .drawBehind { drawLine(palette.border, Offset.Zero, Offset(size.width, 0f), 1.dp.toPx()) }
                .padding(horizontal = 18.dp, vertical = 12.dp),
        )
    }
}

@Composable
private fun SideTab(tab: AppScreen, isActive: Boolean, onOpen: (AppScreen) -> Unit) {
    val palette = NeutrinoTheme.palette
    val color = if (isActive) palette.accent else palette.textMuted
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(6.dp))
            .background(if (isActive) palette.accent.copy(alpha = 0.10f) else palette.surface.copy(alpha = 0f))
            .semantics { selected = isActive }
            .clickable(role = Role.Tab) { onOpen(tab) }
            .padding(horizontal = 12.dp, vertical = 9.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        tab.icon?.let { IconGlyph(it, color, size = 17.dp) }
        BasicText(
            NeutrinoTheme.words.word(tab.titleKey),
            style = NeutrinoTheme.body.copy(color = color, fontSize = 13.sp, fontWeight = FontWeight.Medium),
        )
    }
}
