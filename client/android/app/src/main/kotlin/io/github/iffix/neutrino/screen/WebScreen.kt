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
import io.github.iffix.neutrino.forward.PortForwardJob
import io.github.iffix.neutrino.forward.PortForwardRow
import io.github.iffix.neutrino.forward.PortForwards
import io.github.iffix.neutrino.shell.LocalClientActions
import java.net.URI
import java.net.URISyntaxException

/**
 * The web services the joined hubs publish. Open forwards the entry to this phone's loopback
 * through the hub when it has no forward, reads a fresh token for an entry with
 * `is_token_required`, and opens the browser on the entry's own `.localhost` name, the button
 * showing the job meanwhile. Configure, at the left, opens the local port dialog while the entry
 * is not forwarded; a forwarded row names its loopback address with Copy and Disconnect, as a
 * Ports row does.
 *
 * @param hubs Every hub joined.
 * @param forwards Each entry's forward and job, by entry key.
 * @param onOpen What pressing Open does, with the binding id, the entry id, the address and
 *   whether the page opens with a token.
 */
@Composable
fun WebScreen(
    hubs: List<HubView>,
    forwards: Map<String, PortForwardRow>,
    onOpen: (String, String, String, Boolean) -> Unit,
) {
    val words = NeutrinoTheme.words
    val actions = LocalClientActions.current
    var configuring by remember { mutableStateOf<Triple<String, String, String>?>(null) }
    ServiceList(hubs, "web", "ui.empty_web") { hub, entry, hasDivider ->
        val url = entry.text("url")
        val isTokenRequired = entry.flag("is_token_required")
        val isHealthy = entry.isHealthy != false
        val row = forwards[PortForwards.keyOf(hub.binding.id, entry.id)] ?: PortForwardRow()
        val job = row.job
        val isFree = job == null && !hub.jobs.isRefreshing && !hub.isDisabled
        val loopback = "$FORWARD_BIND_HOST:${row.localPort}"
        val reason = when {
            job != null || hub.jobs.isRefreshing -> null
            hub.isDisabled -> words.word("ui.reason.disabled")
            !isHealthy -> words.word("ui.reason.unhealthy")
            row.isForwarded -> words.word("ui.reason.disconnect_first")
            else -> null
        }
        FeatureRow(
            marker = entryTone(hub, entry, isBusy = job != null),
            hasDivider = hasDivider,
            actions = {
                NeutrinoButton(
                    words.word("ui.configure"),
                    { configuring = Triple(hub.binding.id, entry.id, entry.title) },
                    isSmall = true,
                    isEnabled = isFree && !row.isForwarded,
                )
                NeutrinoButton(
                    words.word(if (job == PortForwardJob.OPENING) job.wordKey else "ui.open"),
                    { onOpen(hub.binding.id, entry.id, url, isTokenRequired) },
                    isSmall = true,
                    isBusy = job == PortForwardJob.OPENING,
                    isEnabled = isHealthy && isFree,
                )
                if (row.isForwarded) {
                    if (job == null) CopyButton(isEnabled = isFree) { actions?.copy(loopback) }
                    NeutrinoButton(
                        words.word(job?.takeIf { it == PortForwardJob.DISCONNECTING }?.wordKey ?: "ui.port_disconnect"),
                        { actions?.disconnectPort(hub.binding.id, entry.id) },
                        tier = if (job == null) ButtonTier.DANGER else ButtonTier.PLAIN,
                        isSmall = true,
                        isBusy = job == PortForwardJob.DISCONNECTING,
                        isEnabled = job == null && !hub.jobs.isRefreshing,
                    )
                }
            },
        ) {
            BasicText(entry.title, style = NeutrinoTheme.rowTitle)
            if (!isHealthy) BasicText(words.word("ui.unhealthy"), style = NeutrinoTheme.note)
            val forwarded = if (row.isForwarded) {
                " → " + words.word("ui.forwarding_to", mapOf("port" to row.localPort))
            } else {
                ""
            }
            BasicText(url + forwarded, style = NeutrinoTheme.mono)
            BasicText(providedBy(hub, entry, hostOf(url)), style = NeutrinoTheme.note)
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

private fun hostOf(url: String): String = try {
    URI(url).host.orEmpty()
} catch (_: URISyntaxException) {
    ""
}

@Preview(widthDp = 400, heightDp = 600)
@Composable
private fun WebScreenPreview() {
    PreviewHubs.Frame(
        mapOf(
            "ui.machine_provided_by" to "由 {hub}:{device} 提供",
            "ui.open" to "打开",
            "ui.configure" to "配置",
        ),
    ) {
        WebScreen(PreviewHubs.all, emptyMap(), onOpen = { _, _, _, _ -> })
    }
}
