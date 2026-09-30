package io.github.iffix.neutrino.screen

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.design.Badge
import io.github.iffix.neutrino.design.DotTone
import io.github.iffix.neutrino.design.FeatureRow
import io.github.iffix.neutrino.design.NeutrinoTheme
import java.net.URI
import java.net.URISyntaxException

/**
 * The web services the joined hubs publish: a press opens one in the browser; one that only a
 * desktop can reach is greyed with its badge.
 *
 * @param hubs Every hub joined.
 * @param onOpen What pressing an entry does, with its address.
 * @param onJoin What pressing Join a hub does.
 */
@Composable
fun WebScreen(hubs: List<HubView>, onOpen: (String) -> Unit, onJoin: () -> Unit) {
    val words = NeutrinoTheme.words
    ServiceList(hubs, "web", "ui.empty_web", onJoin) { hub, entry, hasDivider ->
        val url = entry.text("url")
        val isLocalOnly = entry.flag("is_local_only")
        FeatureRow(
            marker = if (isLocalOnly) DotTone.OFF else DotTone.OK,
            onClick = if (isLocalOnly) null else ({ onOpen(url) }),
            isGreyed = isLocalOnly,
            hasDivider = hasDivider,
            hasChevron = !isLocalOnly,
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                BasicText(entry.title, style = NeutrinoTheme.rowTitle)
                if (isLocalOnly) Badge(words.word("ui.desktop_only"))
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
            "ui.reconnecting" to "正在重新连接 hub",
        ),
    ) { WebScreen(PreviewHubs.all, onOpen = {}, onJoin = {}) }
}
