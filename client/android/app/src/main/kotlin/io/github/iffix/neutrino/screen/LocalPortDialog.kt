package io.github.iffix.neutrino.screen

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
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
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import io.github.iffix.neutrino.FORWARD_FIXED_PORTS
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.ChannelServiceEntry
import io.github.iffix.neutrino.design.ButtonTier
import io.github.iffix.neutrino.design.InputField
import io.github.iffix.neutrino.design.NeutrinoButton
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.design.ReasonLine

/**
 * An app's Configure dialog: one line per entry, its name, its kind and a number field that starts
 * at the entry's number, the person's or else the hub's, then Cancel and Save. A number of the
 * person's, from 1024 to 65535, replaces the hub's on this phone alone, and an empty field goes back
 * to the hub's. A refused Save stays open with its reason, and a disabled Save has its reason under
 * the fields.
 *
 * @param title The app's title.
 * @param entries The app's entries the dialog lists.
 * @param numbers Each entry's number the person set, by entry id, null where it takes the hub's.
 * @param onSave What Save does with each entry's number, null for the hub's: Ok closes the dialog,
 *   a refusal is worded as `ui.reason.<code>`.
 * @param onClose What closing the dialog does.
 */
@Composable
fun LocalPortDialog(
    title: String,
    entries: List<ChannelServiceEntry>,
    numbers: Map<String, Int?>,
    onSave: (Map<String, Int?>) -> ChannelResult<Unit>,
    onClose: () -> Unit,
) {
    val words = NeutrinoTheme.words
    val palette = NeutrinoTheme.palette
    var typed by remember {
        mutableStateOf(entries.associate { it.id to (numbers[it.id] ?: it.localPort).toString() })
    }
    var refusal by remember { mutableStateOf<ChannelResult.Refused?>(null) }
    val reasonKey = localPortReasonKey(typed.values)
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
            BasicText(words.word("ui.app.port_dialog_title", mapOf("app" to title)), style = NeutrinoTheme.rowTitle)
            for (entry in entries) {
                Row(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        BasicText(entry.name.ifEmpty { entry.title }, style = NeutrinoTheme.body)
                        BasicText(kindOf(entry), style = NeutrinoTheme.mono)
                    }
                    InputField(
                        value = typed[entry.id].orEmpty(),
                        onChange = { text ->
                            typed = typed + (entry.id to text.filter { it.isDigit() }.take(5))
                            refusal = null
                        },
                        label = words.word("ui.local_port"),
                        modifier = Modifier.weight(1f),
                        placeholder = entry.localPort.toString(),
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
                        when (val answer = onSave(numbersOf(entries, typed))) {
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
 * @param typed Each entry's field as typed.
 * @return `ui.reason.port_range` while a field holds a number outside 1024 to 65535, else null; an
 *   empty field is the hub's number.
 */
internal fun localPortReasonKey(typed: Collection<String>): String? =
    "ui.reason.port_range".takeIf { typed.any { it.isNotEmpty() && it.toIntOrNull() !in FORWARD_FIXED_PORTS } }

/**
 * The numbers Save keeps: a field holding the hub's number, or nothing, goes back to the hub's.
 *
 * @param entries The app's entries.
 * @param typed Each entry's field as typed.
 * @return Each entry's number by entry id, null for the hub's.
 */
internal fun numbersOf(entries: List<ChannelServiceEntry>, typed: Map<String, String>): Map<String, Int?> =
    entries.associate { entry ->
        val number = typed[entry.id]?.toIntOrNull()
        entry.id to number?.takeIf { it != entry.localPort }
    }

/**
 * An entry's kind as the Apps page names it: `web`, `port`, or `port/udp` for a UDP port.
 *
 * @param entry The entry.
 * @return The kind.
 */
internal fun kindOf(entry: ChannelServiceEntry): String =
    if (entry.protocol == "udp") "${entry.type}/udp" else entry.type

@Preview(widthDp = 400, heightDp = 300)
@Composable
private fun LocalPortDialogPreview() {
    PreviewHubs.Frame(mapOf("ui.local_port" to "本地端口")) {
        val entries = PreviewHubs.all.flatMap { it.services }.filter { it.appId.isNotEmpty() }
        LocalPortDialog("Gitea", entries, emptyMap(), { ChannelResult.Ok(Unit) }, {})
    }
}
