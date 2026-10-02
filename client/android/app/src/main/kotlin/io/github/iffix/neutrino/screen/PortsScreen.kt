package io.github.iffix.neutrino.screen

import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.ui.tooling.preview.Preview
import io.github.iffix.neutrino.FORWARD_BIND_HOST
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.design.ButtonTier
import io.github.iffix.neutrino.design.CopyButton
import io.github.iffix.neutrino.design.ErrorLine
import io.github.iffix.neutrino.design.FeatureRow
import io.github.iffix.neutrino.design.NeutrinoButton
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.design.ReasonLine
import io.github.iffix.neutrino.forward.PortForwardRow
import io.github.iffix.neutrino.forward.PortForwards

/**
 * The ports the joined hubs publish, each forwarded to this phone's loopback on Connect: the
 * button shows the job, a forwarded row names its loopback address with Copy beside Disconnect,
 * and Connect is disabled with its reason while the entry is unhealthy.
 *
 * @param hubs Every hub joined.
 * @param forwards Each entry's forward, by entry key.
 * @param onConnect What pressing Connect does, with the binding id, the entry id, the host and the port.
 * @param onDisconnect What pressing Disconnect does, with the binding id and the entry id.
 * @param onCopy What copying an address does.
 */
@Composable
fun PortsScreen(
    hubs: List<HubView>,
    forwards: Map<String, PortForwardRow>,
    onConnect: (String, String, String, Int) -> Unit,
    onDisconnect: (String, String) -> Unit,
    onCopy: (String) -> Unit,
) {
    val words = NeutrinoTheme.words
    ServiceList(hubs, "port", "ui.empty_ports") { hub, entry, hasDivider ->
        val host = entry.text("host")
        val port = entry.number("port")
        val row = forwards[PortForwards.keyOf(hub.binding.id, entry.id)] ?: PortForwardRow()
        val job = row.job
        val isHealthy = entry.isHealthy != false
        val isFree = job == null && !hub.jobs.isRefreshing && !hub.isDisabled
        val loopback = "$FORWARD_BIND_HOST:${row.localPort}"
        val reason = when {
            job != null || hub.jobs.isRefreshing -> null
            hub.isDisabled -> words.word("ui.reason.disabled")
            !isHealthy && !row.isForwarded -> words.word("ui.reason.unhealthy")
            else -> null
        }
        FeatureRow(
            marker = entryTone(hub, entry, isBusy = job != null),
            hasDivider = hasDivider,
            actions = {
                if (row.isForwarded && job == null) CopyButton(isEnabled = isFree) { onCopy(loopback) }
                NeutrinoButton(
                    label = words.word(
                        when {
                            job != null -> job.wordKey
                            row.isForwarded -> "ui.port_disconnect"
                            else -> "ui.port_connect"
                        },
                    ),
                    onClick = {
                        if (row.isForwarded) {
                            onDisconnect(hub.binding.id, entry.id)
                        } else if (port != null) {
                            onConnect(hub.binding.id, entry.id, host, port)
                        }
                    },
                    tier = if (row.isForwarded && job == null) ButtonTier.DANGER else ButtonTier.PLAIN,
                    isEnabled = isFree && port != null && (isHealthy || row.isForwarded),
                    isBusy = job != null,
                    isSmall = true,
                )
            },
        ) {
            BasicText(entry.title, style = NeutrinoTheme.rowTitle)
            if (!isHealthy) BasicText(words.word("ui.unhealthy"), style = NeutrinoTheme.note)
            val forwarded = if (row.isForwarded) {
                " → " + words.word("ui.forwarding_to", mapOf("port" to row.localPort))
            } else {
                ""
            }
            BasicText("$host:${port ?: ""}$forwarded", style = NeutrinoTheme.mono)
            BasicText(providedBy(hub, entry, host), style = NeutrinoTheme.note)
            ErrorLine(row.error)
            ReasonLine(reason)
        }
    }
}

@Preview(widthDp = 400, heightDp = 600)
@Composable
private fun PortsScreenPreview() {
    PreviewHubs.Frame(
        mapOf(
            "ui.machine_provided_by" to "由 {hub}:{device} 提供",
            "ui.port_connect" to "连接",
            "ui.port_disconnect" to "断开",
            "ui.copy" to "复制",
        ),
    ) {
        PortsScreen(PreviewHubs.all, emptyMap(), onConnect = { _, _, _, _ -> }, onDisconnect = { _, _ -> }, onCopy = {})
    }
}
