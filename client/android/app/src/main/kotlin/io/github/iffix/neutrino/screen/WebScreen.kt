package io.github.iffix.neutrino.screen

import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.ui.tooling.preview.Preview
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.design.FeatureRow
import io.github.iffix.neutrino.design.NeutrinoButton
import io.github.iffix.neutrino.design.NeutrinoTheme
import java.net.URI
import java.net.URISyntaxException

/**
 * The web services the joined hubs publish: Open shows one in the browser; one only a desktop
 * can reach says so and has no button.
 *
 * @param hubs Every hub joined.
 * @param onOpen What pressing Open does, with the address.
 */
@Composable
fun WebScreen(hubs: List<HubView>, onOpen: (String) -> Unit) {
    val words = NeutrinoTheme.words
    ServiceList(hubs, "web", "ui.empty_web") { hub, entry, hasDivider ->
        val url = entry.text("url")
        val isLocalOnly = entry.flag("is_local_only")
        val isHealthy = entry.isHealthy != false
        FeatureRow(
            marker = entryTone(hub, entry),
            hasDivider = hasDivider,
            actions = if (isLocalOnly) {
                null
            } else {
                {
                    NeutrinoButton(
                        words.word("ui.open"),
                        { onOpen(url) },
                        isSmall = true,
                        isEnabled = isHealthy && !hub.jobs.isRefreshing,
                    )
                }
            },
        ) {
            BasicText(entry.title, style = NeutrinoTheme.rowTitle)
            when {
                isLocalOnly -> BasicText(words.word("ui.desktop_only"), style = NeutrinoTheme.note)
                !isHealthy -> BasicText(words.word("ui.unhealthy"), style = NeutrinoTheme.note)
            }
            BasicText(url, style = NeutrinoTheme.mono)
            BasicText(providedBy(hub, entry, hostOf(url)), style = NeutrinoTheme.note)
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
            "ui.desktop_only" to "仅桌面",
            "ui.open" to "打开",
        ),
    ) { WebScreen(PreviewHubs.all, onOpen = {}) }
}
