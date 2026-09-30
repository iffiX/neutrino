package io.github.iffix.neutrino.shell

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.iffix.neutrino.design.AppIcon
import io.github.iffix.neutrino.design.IconGlyph
import io.github.iffix.neutrino.design.NeutrinoTheme

/**
 * The bar over every screen: a back arrow for a screen reached from another, the title, and the
 * virtual network chip.
 *
 * @param title The open screen's title.
 * @param overlayValue What the chip says after its key: this phone's address, or not joined.
 * @param onBack What the back arrow does, or null for a tab's own screen.
 * @param modifier Placement.
 * @param isWide Whether the bar sits beside the sidebar, which pads it wider.
 */
@Composable
fun TopBar(
    title: String,
    overlayValue: String,
    onBack: (() -> Unit)?,
    modifier: Modifier = Modifier,
    isWide: Boolean = false,
) {
    val palette = NeutrinoTheme.palette
    val words = NeutrinoTheme.words
    Row(
        modifier = modifier
            .fillMaxWidth()
            .heightIn(min = if (isWide) 57.dp else 56.dp)
            .background(palette.bg)
            .drawBehind {
                drawLine(palette.border, Offset(0f, size.height), Offset(size.width, size.height), 1.dp.toPx())
            }
            .padding(horizontal = if (isWide) 20.dp else 16.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (onBack != null) {
            val back = words.word("ui.back")
            Box(
                modifier = Modifier
                    .size(32.dp)
                    .clip(RoundedCornerShape(6.dp))
                    .semantics { contentDescription = back }
                    .clickable(role = Role.Button, onClick = onBack),
                contentAlignment = Alignment.Center,
            ) {
                IconGlyph(AppIcon.CHEVRON_LEFT, palette.textMuted, size = 20.dp)
            }
        }
        BasicText(
            title,
            style = NeutrinoTheme.pageTitle,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f),
        )
        Row(
            modifier = Modifier
                .widthIn(max = 220.dp)
                .clip(RoundedCornerShape(50))
                .background(palette.surface)
                .border(1.dp, palette.border, RoundedCornerShape(50))
                .padding(horizontal = 10.dp, vertical = 4.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            BasicText(
                words.word("ui.overlay"),
                style = NeutrinoTheme.mono.copy(color = palette.textFaint, fontSize = 10.sp, letterSpacing = 0.8.sp),
            )
            BasicText(
                overlayValue,
                style = NeutrinoTheme.mono.copy(color = palette.text),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}
