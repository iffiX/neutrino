package io.github.iffix.neutrino.screen

import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.ui.tooling.preview.Preview
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.design.ErrorLine
import io.github.iffix.neutrino.design.FeatureRow
import io.github.iffix.neutrino.design.NeutrinoButton
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.design.ReasonLine
import io.github.iffix.neutrino.remotedesktop.RemoteDesktopSessions

/**
 * The desktops the machines of the joined hubs share, each with Connect: the button shows the
 * job while the address and seat password come from the hub, then the viewer opens.
 *
 * @param hubs Every hub joined.
 * @param connecting The entries whose Connect runs, by entry key.
 * @param errors The code each entry's last Connect ended in, by entry key.
 * @param viewingKey The entry the open viewer shows, or null.
 * @param onConnect What pressing Connect does, with the binding id, the entry id and the viewer's title.
 */
@Composable
fun RemoteDesktopScreen(
    hubs: List<HubView>,
    connecting: Set<String>,
    errors: Map<String, ChannelResult.Refused>,
    viewingKey: String?,
    onConnect: (String, String, String) -> Unit,
) {
    val words = NeutrinoTheme.words
    ServiceList(hubs, "rdp", "ui.empty_desktops") { hub, entry, hasDivider ->
        val key = RemoteDesktopSessions.keyOf(hub.binding.id, entry.id)
        val host = entry.text("host")
        val isHealthy = entry.isHealthy != false
        val isBusy = key in connecting
        val reason = when {
            !isHealthy -> entry.descriptionCode.takeIf { it.isNotEmpty() }?.let { words.refusal(it) }
                ?: words.word("ui.unhealthy")

            viewingKey != null -> words.word("ui.reason_viewer_open")

            else -> null
        }
        FeatureRow(
            marker = entryTone(hub, entry, isBusy),
            hasDivider = hasDivider,
            actions = {
                NeutrinoButton(
                    label = words.word(if (isBusy) "ui.job.connecting" else "ui.rdp_connect"),
                    onClick = {
                        val name = hub.binding.title + ":" + entry.deviceName.ifEmpty { entry.title }
                        onConnect(hub.binding.id, entry.id, name)
                    },
                    isEnabled = reason == null && !isBusy && !hub.jobs.isRefreshing,
                    isBusy = isBusy,
                    isSmall = true,
                )
            },
        ) {
            BasicText(entry.title, style = NeutrinoTheme.rowTitle)
            if (viewingKey == key) BasicText(words.word("ui.rdp_open"), style = NeutrinoTheme.note)
            BasicText("$host:${entry.number("port") ?: ""}", style = NeutrinoTheme.mono)
            BasicText(providedBy(hub, entry, host), style = NeutrinoTheme.note)
            ErrorLine(errors[key])
            ReasonLine(reason)
        }
    }
}

@Preview(widthDp = 400, heightDp = 600)
@Composable
private fun RemoteDesktopScreenPreview() {
    PreviewHubs.Frame(
        mapOf(
            "ui.machine_provided_by" to "由 {hub}:{device} 提供",
            "ui.rdp_connect" to "连接",
            "ui.unhealthy" to "当前无法访问",
        ),
    ) {
        RemoteDesktopScreen(PreviewHubs.all, emptySet(), emptyMap(), null, onConnect = { _, _, _ -> })
    }
}
