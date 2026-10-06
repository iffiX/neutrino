package io.github.iffix.neutrino.screen

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.selection.selectable
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
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import io.github.iffix.neutrino.FORWARD_FIXED_PORTS
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.design.ButtonTier
import io.github.iffix.neutrino.design.InputField
import io.github.iffix.neutrino.design.NeutrinoButton
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.design.ReasonLine
import io.github.iffix.neutrino.design.SelectedMark
import io.github.iffix.neutrino.forward.LocalPortChoice

/**
 * The Configure dialog of a forwardable entry: one choice, Local port, Auto or Fixed with a
 * number from 1024 to 65535, then Cancel and Save. A refused Save stays open with its reason, and a
 * disabled Save has its reason under the field.
 *
 * @param title The entry's title.
 * @param initial The entry's local port as the table holds it.
 * @param onSave What Save does with the choice: Ok closes the dialog, a refusal is worded as `ui.reason.<code>`.
 * @param onClose What closing the dialog does.
 */
@Composable
fun LocalPortDialog(
    title: String,
    initial: LocalPortChoice,
    onSave: (LocalPortChoice) -> ChannelResult<Unit>,
    onClose: () -> Unit,
) {
    val words = NeutrinoTheme.words
    val palette = NeutrinoTheme.palette
    var isFixed by remember { mutableStateOf(initial.isFixed) }
    var number by remember { mutableStateOf(if (initial.isFixed) initial.port.toString() else "") }
    var refusal by remember { mutableStateOf<ChannelResult.Refused?>(null) }
    val fixed = number.toIntOrNull()?.takeIf { it in FORWARD_FIXED_PORTS }
    val reasonKey = localPortReasonKey(isFixed, number)
    val shape = RoundedCornerShape(10.dp)
    Dialog(onDismissRequest = onClose) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .clip(shape)
                .background(palette.surface)
                .border(1.dp, palette.border, shape)
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                BasicText(words.word("ui.local_port"), style = NeutrinoTheme.rowTitle)
                BasicText(title, style = NeutrinoTheme.note)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                Chip(words.word("ui.local_port_auto"), isSelected = !isFixed) {
                    isFixed = false
                    refusal = null
                }
                Chip(words.word("ui.local_port_fixed"), isSelected = isFixed) {
                    isFixed = true
                    refusal = null
                }
                if (isFixed) {
                    InputField(
                        value = number,
                        onChange = { typed ->
                            number = typed.filter { it.isDigit() }.take(5)
                            refusal = null
                        },
                        label = words.word("ui.local_port"),
                        modifier = Modifier.weight(1f),
                        placeholder = "${FORWARD_FIXED_PORTS.first}–${FORWARD_FIXED_PORTS.last}",
                    )
                }
            }
            refusal?.let {
                BasicText(
                    words.word("ui.reason.${it.code}", it.wordParams),
                    style = NeutrinoTheme.note.copy(color = palette.error),
                )
            }
            if (refusal == null) ReasonLine(reasonKey?.let { words.word(it) })
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.End),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                NeutrinoButton(words.word("ui.cancel"), onClose, tier = ButtonTier.GHOST)
                NeutrinoButton(
                    words.word("ui.save"),
                    {
                        val choice = if (isFixed) {
                            LocalPortChoice(
                                isFixed = true,
                                port = fixed ?: 0,
                            )
                        } else {
                            LocalPortChoice()
                        }
                        when (val answer = onSave(choice)) {
                            is ChannelResult.Ok -> onClose()
                            is ChannelResult.Refused -> refusal = answer
                        }
                    },
                    tier = ButtonTier.PRIMARY,
                    isEnabled = reasonKey == null,
                )
            }
        }
    }
}

/**
 * Why Save is disabled in the local port dialog.
 *
 * @param isFixed Whether Fixed is chosen.
 * @param number The number typed.
 * @return `ui.reason.port_range` while Fixed is chosen and the number is not one from 1024 to
 *   65535, else null.
 */
internal fun localPortReasonKey(isFixed: Boolean, number: String): String? =
    "ui.reason.port_range".takeIf { isFixed && number.toIntOrNull()?.takeIf { it in FORWARD_FIXED_PORTS } == null }

@Composable
private fun Chip(label: String, isSelected: Boolean, onSelect: () -> Unit) {
    val mark = SelectedMark.of(NeutrinoTheme.palette, isSelected)
    val shape = RoundedCornerShape(6.dp)
    BasicText(
        label,
        style = NeutrinoTheme.body.copy(color = mark.text),
        modifier = Modifier
            .clip(shape)
            .background(mark.fill)
            .border(1.dp, mark.border, shape)
            .selectable(selected = isSelected, role = Role.RadioButton, onClick = onSelect)
            .padding(horizontal = 12.dp, vertical = 6.dp),
    )
}

@Preview(widthDp = 400, heightDp = 300)
@Composable
private fun LocalPortDialogPreview() {
    PreviewHubs.Frame(mapOf("ui.local_port" to "本地端口", "ui.local_port_auto" to "自动", "ui.local_port_fixed" to "指定")) {
        LocalPortDialog("VS Code", LocalPortChoice(isFixed = true, port = 8000), { ChannelResult.Ok(Unit) }, {})
    }
}
