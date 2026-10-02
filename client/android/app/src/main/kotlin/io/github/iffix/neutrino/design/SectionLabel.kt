package io.github.iffix.neutrino.design

import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp

/**
 * The panel's section label: a group's name over its rows, small, uppercase and muted.
 *
 * @param text The group's name.
 * @param modifier Placement.
 */
@Composable
fun SectionLabel(text: String, modifier: Modifier = Modifier) {
    BasicText(
        text.uppercase(),
        style = NeutrinoTheme.note.copy(fontSize = 11.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.09.em),
        modifier = modifier,
    )
}
