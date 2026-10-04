package io.github.iffix.neutrino.screen

import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.tooling.preview.Preview
import io.github.iffix.neutrino.FORWARD_BIND_HOST
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.design.ButtonTier
import io.github.iffix.neutrino.design.CopyButton
import io.github.iffix.neutrino.design.ErrorLine
import io.github.iffix.neutrino.design.FeatureRow
import io.github.iffix.neutrino.design.NeutrinoButton
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.design.ReasonLine
import io.github.iffix.neutrino.forward.LocalPortChoice
import io.github.iffix.neutrino.forward.PortForwardRow
import io.github.iffix.neutrino.forward.PortForwards
import io.github.iffix.neutrino.shell.LocalClientActions

/**
 * The ports the joined hubs publish, each forwarded to this phone's loopback through the hub on Connect: the
 * button shows the job, a forwarded row names its loopback address with Copy beside Disconnect,
 * and Connect is disabled with its reason while the entry is unhealthy. Configure, at the left,
 * opens the local port dialog while the entry is not forwarded.
 *
 * @param hubs Every hub joined.
 * @param forwards Each entry's forward, by entry key.
 * @param onConnect What pressing Connect does, with the binding id, the entry id and the port.
 * @param onDisconnect What pressing Disconnect does, with the binding id and the entry id.
 * @param onCopy What copying an address does.
 */
@Composable
fun PortsScreen(
    hubs: List<HubView>,
    forwards: Map<String, PortForwardRow>,
    onConnect: (String, String, Int) -> Unit,
    onDisconnect: (String, String) -> Unit,
    onCopy: (String) -> Unit,
) {
    val words = NeutrinoTheme.words
    val actions = LocalClientActions.current
    var configuring by remember { mutableStateOf<Triple<String, String, String>?>(null) }
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
            row.isForwarded -> words.word("ui.reason.disconnect_first")
            !isHealthy -> words.word("ui.reason.unhealthy")
            else -> null
        }
        FeatureRow(
            marker = entryTone(hub, entry, isBusy = job != null),
            hasDivider = hasDivider,
            actions = {
                NeutrinoButton(
                    label = words.word("ui.configure"),
                    onClick = { configuring = Triple(hub.binding.id, entry.id, entry.title) },
                    isEnabled = isFree && !row.isForwarded,
                    isSmall = true,
                )
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
                            onConnect(hub.binding.id, entry.id, port)
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
    configuring?.let { (bindingId, entryId, title) ->
        LocalPortDialog(
            title = title,
            initial = remember(bindingId, entryId) { actions?.localPortOf(bindingId, entryId) ?: LocalPortChoice() },
            onSave = { actions?.configurePort(bindingId, entryId, it) ?: ChannelResult.Ok(Unit) },
            onClose = { configuring = null },
        )
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
            "ui.configure" to "配置",
            "ui.copy" to "复制",
        ),
    ) {
        PortsScreen(PreviewHubs.all, emptyMap(), onConnect = { _, _, _ -> }, onDisconnect = { _, _ -> }, onCopy = {})
    }
}
