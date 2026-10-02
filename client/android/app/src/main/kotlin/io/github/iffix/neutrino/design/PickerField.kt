package io.github.iffix.neutrino.design

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Popup
import androidx.compose.ui.window.PopupProperties

/**
 * A drop-down field: the chosen option, and the list of every option under it once pressed.
 *
 * @param options Every option as `value to label`, in the order they are listed.
 * @param selected The chosen option's value.
 * @param onSelect What choosing an option does, with its value.
 * @param modifier Placement.
 * @param head A line over the list.
 * @param isEnabled Whether the field opens; a disabled field is drawn in the faint and muted colours.
 * @param isWide Whether the field fills the width.
 */
@Composable
fun PickerField(
    options: List<Pair<String, String>>,
    selected: String,
    onSelect: (String) -> Unit,
    modifier: Modifier = Modifier,
    head: String? = null,
    isEnabled: Boolean = true,
    isWide: Boolean = true,
) {
    val palette = NeutrinoTheme.palette
    var isOpen by remember { mutableStateOf(false) }
    var fieldSize by remember { mutableStateOf(IntSize.Zero) }
    val density = LocalDensity.current
    val shape = RoundedCornerShape(6.dp)
    val label = options.firstOrNull { it.first == selected }?.second ?: selected
    Box(modifier = modifier) {
        Row(
            modifier = (if (isWide) Modifier.fillMaxWidth() else Modifier)
                .onSizeChanged { fieldSize = it }
                .clip(shape)
                .background(palette.bg)
                .border(
                    1.dp,
                    when {
                        !isEnabled -> palette.textFaint
                        isOpen -> palette.accent
                        else -> palette.border
                    },
                    shape,
                )
                .clickable(enabled = isEnabled, role = Role.DropdownList) { isOpen = !isOpen }
                .padding(horizontal = 11.dp, vertical = 9.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            BasicText(
                label,
                style = NeutrinoTheme.mono.copy(color = if (isEnabled) palette.text else palette.textMuted),
                modifier = Modifier.weight(1f, isWide),
            )
            IconGlyph(AppIcon.CHEVRON_DOWN, if (isEnabled) palette.textMuted else palette.textFaint, size = 12.dp)
        }
        if (isOpen) {
            Popup(
                offset = IntOffset(0, fieldSize.height + with(density) { 4.dp.roundToPx() }),
                onDismissRequest = { isOpen = false },
                properties = PopupProperties(focusable = true),
            ) {
                Column(
                    modifier = Modifier
                        .width(with(density) { fieldSize.width.toDp() }.coerceAtLeast(176.dp))
                        .shadow(12.dp, RoundedCornerShape(8.dp), ambientColor = palette.shadow)
                        .clip(RoundedCornerShape(8.dp))
                        .background(palette.bg)
                        .border(1.dp, palette.border, RoundedCornerShape(8.dp))
                        .padding(4.dp),
                ) {
                    if (head != null) {
                        BasicText(
                            head,
                            style = NeutrinoTheme.note.copy(color = palette.textFaint),
                            modifier = Modifier.padding(10.dp, 4.dp),
                        )
                    }
                    for ((value, text) in options) {
                        val isOn = value == selected
                        BasicText(
                            text = text,
                            style = NeutrinoTheme.mono.copy(color = if (isOn) palette.accent else palette.text),
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(6.dp))
                                .background(if (isOn) palette.accentWash else palette.bg)
                                .clickable(role = Role.Button) {
                                    isOpen = false
                                    onSelect(value)
                                }
                                .padding(horizontal = 10.dp, vertical = 8.dp),
                        )
                    }
                }
            }
        }
    }
}
