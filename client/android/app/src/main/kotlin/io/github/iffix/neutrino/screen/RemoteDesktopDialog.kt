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
import io.github.iffix.neutrino.design.ButtonTier
import io.github.iffix.neutrino.design.NeutrinoButton
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.design.PickerField
import io.github.iffix.neutrino.remotedesktop.RemoteDesktopChoice
import io.github.iffix.neutrino.remotedesktop.RemoteDesktopCodec
import io.github.iffix.neutrino.remotedesktop.RemoteDesktopQuality

/**
 * The Configure dialog of a shared desktop: a Codec picker (Auto, then each codec the core
 * offers) and a Quality picker, then Cancel and Save; the next Connect asks for the choice.
 *
 * @param title The entry's title.
 * @param codecs The codecs the core offers, Auto first.
 * @param initial The choice kept for the entry.
 * @param onSave What Save does with the choice.
 * @param onClose What closing the dialog does.
 */
@Composable
fun RemoteDesktopDialog(
    title: String,
    codecs: List<RemoteDesktopCodec>,
    initial: RemoteDesktopChoice,
    onSave: (RemoteDesktopChoice) -> Unit,
    onClose: () -> Unit,
) {
    val words = NeutrinoTheme.words
    val palette = NeutrinoTheme.palette
    var codec by remember { mutableStateOf(initial.codec.takeIf { it in codecs } ?: RemoteDesktopCodec.AUTO) }
    var quality by remember { mutableStateOf(initial.quality) }
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
                BasicText(words.word("ui.rdp_configure_title"), style = NeutrinoTheme.rowTitle)
                BasicText(title, style = NeutrinoTheme.note)
            }
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                BasicText(words.word("ui.rdp_codec"), style = NeutrinoTheme.fieldLabel)
                PickerField(
                    options = codecs.map { it.coreName to it.title.ifEmpty { words.word("ui.rdp_codec_auto") } },
                    selected = codec.coreName,
                    onSelect = { codec = RemoteDesktopCodec.of(it) },
                )
            }
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                BasicText(words.word("ui.rdp_quality"), style = NeutrinoTheme.fieldLabel)
                PickerField(
                    options = RemoteDesktopQuality.entries.map { it.coreName to words.word(it.wordKey) },
                    selected = quality.coreName,
                    onSelect = { quality = RemoteDesktopQuality.of(it) },
                )
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.End),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                NeutrinoButton(words.word("ui.cancel"), onClose, tier = ButtonTier.GHOST)
                NeutrinoButton(
                    words.word("ui.save"),
                    {
                        onSave(RemoteDesktopChoice(codec, quality))
                        onClose()
                    },
                    tier = ButtonTier.PRIMARY,
                )
            }
        }
    }
}

@Preview(widthDp = 400, heightDp = 400)
@Composable
private fun RemoteDesktopDialogPreview() {
    PreviewHubs.Frame(mapOf("ui.rdp_codec" to "编码", "ui.rdp_quality" to "画质")) {
        RemoteDesktopDialog("Argon", RemoteDesktopCodec.entries, RemoteDesktopChoice(), {}, {})
    }
}
