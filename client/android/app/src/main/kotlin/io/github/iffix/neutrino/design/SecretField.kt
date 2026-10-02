package io.github.iffix.neutrino.design

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * A labelled secret in a mono box with the eye toggle inside the box at its right end, as the
 * panel's password field, and the controls that act on it after the box. The box shrinks on a
 * narrow screen and the controls keep their size; a masked value stays on one line.
 *
 * @param label The field's label.
 * @param value What the box shows: the secret, or its masked form.
 * @param isShown Whether the secret is shown in full.
 * @param onToggle What the eye toggle does.
 * @param modifier Placement.
 * @param controls The buttons after the box.
 */
@Composable
fun SecretField(
    label: String,
    value: String,
    isShown: Boolean,
    onToggle: () -> Unit,
    modifier: Modifier = Modifier,
    controls: @Composable () -> Unit = {},
) {
    val palette = NeutrinoTheme.palette
    val words = NeutrinoTheme.words
    val shape = RoundedCornerShape(6.dp)
    val eye = words.word(if (isShown) "ui.key_hide" else "ui.key_show")
    Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(6.dp)) {
        BasicText(label, style = NeutrinoTheme.fieldLabel)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            Row(
                modifier = Modifier
                    .weight(1f)
                    .clip(shape)
                    .background(palette.bg)
                    .border(1.dp, palette.border, shape)
                    .padding(start = 11.dp, end = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                BasicText(
                    value,
                    style = NeutrinoTheme.mono.copy(color = palette.text, fontSize = 13.sp),
                    modifier = Modifier.weight(1f).padding(vertical = 8.dp),
                    maxLines = if (isShown) Int.MAX_VALUE else 1,
                    overflow = TextOverflow.Clip,
                )
                Box(
                    modifier = Modifier
                        .clip(shape)
                        .semantics { contentDescription = eye }
                        .clickable(role = Role.Switch, onClick = onToggle)
                        .padding(6.dp),
                ) {
                    IconGlyph(if (isShown) AppIcon.EYE_OFF else AppIcon.EYE, palette.textMuted, size = 16.dp)
                }
            }
            controls()
        }
    }
}
