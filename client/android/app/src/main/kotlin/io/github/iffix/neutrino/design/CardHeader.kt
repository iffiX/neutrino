package io.github.iffix.neutrino.design

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * The panel's card header: the card's title over its body.
 *
 * @param title The card's title.
 * @param modifier Placement.
 */
@Composable
fun CardHeader(title: String, modifier: Modifier = Modifier) {
    BasicText(
        title,
        style = NeutrinoTheme.body.copy(fontSize = 16.sp, lineHeight = 22.sp, fontWeight = FontWeight.SemiBold),
        modifier = modifier.fillMaxWidth().padding(bottom = 16.dp),
    )
}
