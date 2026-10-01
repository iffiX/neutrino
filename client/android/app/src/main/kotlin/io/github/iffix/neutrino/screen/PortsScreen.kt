package io.github.iffix.neutrino.screen

import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.ui.tooling.preview.Preview
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.design.CopyButton
import io.github.iffix.neutrino.design.FeatureRow
import io.github.iffix.neutrino.design.NeutrinoTheme

/**
 * The ports the joined hubs publish, each with its address and port to copy; the phone forwards
 * nothing.
 *
 * @param hubs Every hub joined.
 * @param onCopy What copying an address does.
 */
@Composable
fun PortsScreen(hubs: List<HubView>, onCopy: (String) -> Unit) {
    val words = NeutrinoTheme.words
    ServiceList(hubs, "port", "ui.empty_ports") { hub, entry, hasDivider ->
        val host = entry.text("host")
        val address = "$host:${entry.number("port") ?: ""}"
        FeatureRow(
            marker = entryTone(hub, entry),
            hasDivider = hasDivider,
            actions = { CopyButton(isEnabled = !hub.jobs.isRefreshing) { onCopy(address) } },
        ) {
            BasicText(entry.title, style = NeutrinoTheme.rowTitle)
            if (entry.isHealthy == false) BasicText(words.word("ui.unhealthy"), style = NeutrinoTheme.note)
            BasicText(address, style = NeutrinoTheme.mono)
            BasicText(providedBy(hub, entry, host), style = NeutrinoTheme.note)
        }
    }
}

@Preview(widthDp = 400, heightDp = 600)
@Composable
private fun PortsScreenPreview() {
    PreviewHubs.Frame(mapOf("ui.machine_provided_by" to "由 {hub}:{device} 提供", "ui.copy" to "复制")) {
        PortsScreen(PreviewHubs.all, onCopy = {})
    }
}
