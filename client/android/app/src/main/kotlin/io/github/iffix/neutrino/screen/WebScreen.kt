package io.github.iffix.neutrino.screen

import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.ui.tooling.preview.Preview
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.design.ErrorLine
import io.github.iffix.neutrino.design.FeatureRow
import io.github.iffix.neutrino.design.NeutrinoButton
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.design.ReasonLine
import io.github.iffix.neutrino.forward.PortForwardRow
import io.github.iffix.neutrino.forward.PortForwards
import java.net.URI
import java.net.URISyntaxException

/**
 * The web services the joined hubs publish: Open shows one in the browser, and Open locally
 * forwards a local-only one to this phone's loopback, takes its token from the hub and opens the
 * loopback address, the button showing the job meanwhile.
 *
 * @param hubs Every hub joined.
 * @param forwards Each local-only entry's forward and job, by entry key.
 * @param onOpen What pressing Open does, with the address.
 * @param onOpenLocal What pressing Open locally does, with the binding id, the entry id and the address.
 */
@Composable
fun WebScreen(
    hubs: List<HubView>,
    forwards: Map<String, PortForwardRow>,
    onOpen: (String) -> Unit,
    onOpenLocal: (String, String, String) -> Unit,
) {
    val words = NeutrinoTheme.words
    ServiceList(hubs, "web", "ui.empty_web") { hub, entry, hasDivider ->
        val url = entry.text("url")
        val isLocalOnly = entry.flag("is_local_only")
        val isHealthy = entry.isHealthy != false
        val row = forwards[PortForwards.keyOf(hub.binding.id, entry.id)] ?: PortForwardRow()
        val job = row.job
        val reason = when {
            job != null || hub.jobs.isRefreshing -> null
            hub.isDisabled -> words.word("ui.reason.disabled")
            !isHealthy -> words.word("ui.reason.unhealthy")
            else -> null
        }
        FeatureRow(
            marker = entryTone(hub, entry, isBusy = job != null),
            hasDivider = hasDivider,
            actions = {
                NeutrinoButton(
                    words.word(
                        when {
                            job != null -> job.wordKey
                            isLocalOnly -> "ui.open_local"
                            else -> "ui.open"
                        },
                    ),
                    { if (isLocalOnly) onOpenLocal(hub.binding.id, entry.id, url) else onOpen(url) },
                    isSmall = true,
                    isBusy = job != null,
                    isEnabled = isHealthy && job == null && !hub.jobs.isRefreshing && !hub.isDisabled,
                )
            },
        ) {
            BasicText(entry.title, style = NeutrinoTheme.rowTitle)
            if (!isHealthy) BasicText(words.word("ui.unhealthy"), style = NeutrinoTheme.note)
            BasicText(url, style = NeutrinoTheme.mono)
            BasicText(providedBy(hub, entry, hostOf(url)), style = NeutrinoTheme.note)
            ErrorLine(row.error)
            ReasonLine(reason)
        }
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
            "ui.open_local" to "本机打开",
            "ui.open" to "打开",
        ),
    ) { WebScreen(PreviewHubs.all, emptyMap(), onOpen = {}, onOpenLocal = { _, _, _ -> }) }
}
