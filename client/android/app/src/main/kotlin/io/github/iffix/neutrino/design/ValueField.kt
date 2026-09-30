package io.github.iffix.neutrino.design

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * A labelled value in a box, with the controls that act on it at its end.
 *
 * @param label The field's label.
 * @param value What the box shows.
 * @param modifier Placement.
 * @param controls The buttons after the box.
 */
@Composable
fun ValueField(label: String, value: String, modifier: Modifier = Modifier, controls: @Composable () -> Unit = {}) {
    val palette = NeutrinoTheme.palette
    val shape = RoundedCornerShape(6.dp)
    Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(6.dp)) {
        BasicText(label, style = NeutrinoTheme.fieldLabel)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            BasicText(
                value,
                style = NeutrinoTheme.mono.copy(color = palette.text, fontSize = 13.sp),
                modifier = Modifier
                    .weight(1f)
                    .clip(shape)
                    .background(palette.bg)
                    .border(1.dp, palette.border, shape)
                    .padding(horizontal = 11.dp, vertical = 8.dp),
            )
            controls()
        }
    }
}
