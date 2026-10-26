package io.github.iffix.neutrino.screen

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import io.github.iffix.neutrino.FORWARD_BIND_HOST
import io.github.iffix.neutrino.channel.ChannelApp
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.ChannelServiceEntry
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.design.Badge
import io.github.iffix.neutrino.design.ButtonTier
import io.github.iffix.neutrino.design.DotTone
import io.github.iffix.neutrino.design.ErrorLine
import io.github.iffix.neutrino.design.FeatureRow
import io.github.iffix.neutrino.design.NeutrinoButton
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.design.ReasonLine
import io.github.iffix.neutrino.design.ScreenList
import io.github.iffix.neutrino.design.cardRows
import io.github.iffix.neutrino.design.gap
import io.github.iffix.neutrino.forward.PortForwardJob
import io.github.iffix.neutrino.forward.PortForwardRow
import io.github.iffix.neutrino.forward.PortForwards
import io.github.iffix.neutrino.shell.LocalClientActions

/**
 * The apps the joined hubs publish, one row each: the title with its source, the machine, and one
 * mono line per `web` and `port` entry with its kind and its fixed local address, the `ssh` entries
 * left out on a phone. Use forwards every entry and opens the browser at the first `http` or
 * `https` entry, Configure opens the local port dialog while the app is not in use, and Stop ends
 * the app's forwards while it is.
 *
 * @param hubs Every hub joined.
 * @param forwards Each app's row, by key `<binding>/<app>`.
 * @param portOf The local port an entry listens on, the person's or the hub's, by binding id and entry.
 * @param onUse What pressing Use does, with the binding id and the app id.
 */
@Composable
fun AppsScreen(
    hubs: List<HubView>,
    forwards: Map<String, PortForwardRow>,
    portOf: (String, ChannelServiceEntry) -> Int,
    onUse: (String, String) -> Unit,
) {
    val words = NeutrinoTheme.words
    val actions = LocalClientActions.current
    var configuring by remember { mutableStateOf<Pair<HubView, ChannelApp>?>(null) }
    val apps = hubs.filter { it.isConnected }.flatMap { hub ->
        hub.apps.map { hub to it }.filter { (_, app) -> entriesOf(hub, app).isNotEmpty() }
    }
    val down = hubs.filterNot { it.isConnected }
    ScreenList {
        when {
            hubs.isEmpty() -> sentence(words.word("ui.services_wait_join"))

            apps.isEmpty() -> sentence(words.word("ui.empty_apps"))

            else -> cardRows(apps, key = { (hub, app) -> "${hub.binding.id}/${app.id}" }) { (hub, app), divider ->
                AppRow(
                    hub,
                    app,
                    forwards[PortForwards.keyOf(hub.binding.id, app.id)] ?: PortForwardRow(),
                    portOf,
                    divider,
                    onUse = { onUse(hub.binding.id, app.id) },
                    onConfigure = { configuring = hub to app },
                    onStop = { actions?.stopApp(hub.binding.id, app.id) },
                )
            }
        }
        if (down.isNotEmpty()) {
            gap()
            cardRows(down, key = { "down-${it.binding.id}" }) { hub, hasDivider ->
                FeatureRow(marker = hubTone(hub), isGreyed = true, hasDivider = hasDivider) {
                    BasicText(hub.binding.title, style = NeutrinoTheme.rowTitle)
                    BasicText(hubStateWord(hub, words, System.currentTimeMillis()), style = NeutrinoTheme.note)
                }
            }
        }
    }
    configuring?.let { (hub, app) ->
        val bindingId = hub.binding.id
        LocalPortDialog(
            title = app.title,
            entries = entriesOf(hub, app),
            numbers = remember(bindingId, app.id) { actions?.appNumbersOf(bindingId, app.id).orEmpty() },
            onSave = { actions?.configureApp(bindingId, app.id, it) ?: ChannelResult.Ok(Unit) },
            onClose = { configuring = null },
        )
    }
}

@Composable
private fun AppRow(
    hub: HubView,
    app: ChannelApp,
    row: PortForwardRow,
    portOf: (String, ChannelServiceEntry) -> Int,
    hasDivider: Boolean,
    onUse: () -> Unit,
    onConfigure: () -> Unit,
    onStop: () -> Unit,
) {
    val words = NeutrinoTheme.words
    val entries = entriesOf(hub, app)
    val job = row.job
    val isUsable = entries.any { it.isHealthy != false }
    val isFree = job == null && !hub.jobs.isRefreshing
    FeatureRow(
        marker = appTone(hub, entries, job != null),
        hasDivider = hasDivider,
        actions = {
            NeutrinoButton(
                words.word(if (job == PortForwardJob.OPENING) job.wordKey else "ui.app.use"),
                onUse,
                tier = ButtonTier.PRIMARY,
                isSmall = true,
                isBusy = job == PortForwardJob.OPENING,
                isEnabled = isFree && isUsable && !hub.isDisabled,
            )
            NeutrinoButton(
                words.word("ui.app.configure"),
                onConfigure,
                isSmall = true,
                isEnabled = isFree && !row.isInUse,
            )
            if (row.isInUse) {
                NeutrinoButton(
                    words.word(if (job == PortForwardJob.DISCONNECTING) job.wordKey else "ui.app.stop"),
                    onStop,
                    tier = if (job == null) ButtonTier.DANGER else ButtonTier.PLAIN,
                    isSmall = true,
                    isBusy = job == PortForwardJob.DISCONNECTING,
                    isEnabled = job == null,
                )
            }
        },
    ) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            BasicText(app.title, style = NeutrinoTheme.rowTitle)
            Badge(words.word("ui.app_source.${app.source.ifEmpty { "module" }}"))
        }
        for (entry in entries) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                val address = localAddressOf(app, entry, portOf(hub.binding.id, entry))
                BasicText("${kindOf(entry)}  $address", style = NeutrinoTheme.mono)
                if (entry.isHealthy == false) BasicText(words.word("ui.unhealthy"), style = NeutrinoTheme.note)
            }
        }
        BasicText(
            words.word("ui.machine_provided_by", mapOf("hub" to hub.binding.title, "device" to app.deviceName)),
            style = NeutrinoTheme.note,
        )
        ErrorLine(row.error)
        if (isFree) ReasonLine(appReasonKey(hub, entries, row)?.let { words.word(it) })
    }
}

/**
 * An app's `web` and `port` entries, in the hub's order; a phone leaves the `ssh` ones out.
 *
 * @param hub The hub that publishes the app.
 * @param app The app.
 * @return The entries.
 */
internal fun entriesOf(hub: HubView, app: ChannelApp): List<ChannelServiceEntry> =
    hub.services.filter { it.appId == app.id && (it.type == "web" || it.type == "port") }

/**
 * An entry's local address as the Apps page shows it: `<scheme>://<local name>:<port><path>` for a
 * `web` entry, `<local name>:<port>` for a `port` entry with `/udp` after a UDP one.
 *
 * @param app The app, whose local name the address carries.
 * @param entry The entry.
 * @param port The local port it listens on.
 * @param host The host the phone opens apps under, or null for the app's own local name.
 * @return The address.
 */
internal fun localAddressOf(app: ChannelApp, entry: ChannelServiceEntry, port: Int, host: String? = null): String {
    val name = host ?: app.localName.ifEmpty { FORWARD_BIND_HOST }
    if (entry.type == "web") {
        val target = PortForwards.targetOf(entry.text("url"))
        if (target != null) return "${target.first}://$name:$port${target.second}"
    }
    return if (entry.protocol == "udp") "$name:$port/udp" else "$name:$port"
}

/**
 * Why an app's buttons are disabled.
 *
 * @param hub The hub that publishes the app.
 * @param entries The app's entries.
 * @param row The app's row.
 * @return `ui.reason.disabled` while the hub switched this phone off, `ui.reason.unhealthy` while
 *   no entry is reachable, `ui.reason.disconnect_first` for Configure while the app is in use, else null.
 */
internal fun appReasonKey(hub: HubView, entries: List<ChannelServiceEntry>, row: PortForwardRow): String? = when {
    hub.isDisabled -> "ui.reason.disabled"
    entries.none { it.isHealthy != false } -> "ui.reason.unhealthy"
    row.isInUse -> "ui.reason.disconnect_first"
    else -> null
}

/**
 * The dot of an app's row: pulsing while its hub refreshes or its own job runs, green while some
 * entry is reachable, amber when none is.
 *
 * @param hub The hub that publishes the app.
 * @param entries The app's entries.
 * @param isBusy Whether the app's own job runs.
 * @return The tone.
 */
internal fun appTone(hub: HubView, entries: List<ChannelServiceEntry>, isBusy: Boolean): DotTone = when {
    isBusy || hub.jobs.isRefreshing -> DotTone.PULSE
    entries.none { it.isHealthy != false } -> DotTone.WAIT
    else -> DotTone.OK
}

private fun androidx.compose.foundation.lazy.LazyListScope.sentence(text: String) {
    cardRows(listOf(text), key = { "sentence" }) { line, _ ->
        FeatureRow(hasDivider = false) { BasicText(line, style = NeutrinoTheme.body) }
    }
}

@Preview(widthDp = 400, heightDp = 600)
@Composable
private fun AppsScreenPreview() {
    PreviewHubs.Frame(mapOf("ui.app.use" to "使用", "ui.app.configure" to "配置", "ui.app.stop" to "停止")) {
        AppsScreen(PreviewHubs.all, emptyMap(), portOf = { _, entry -> entry.localPort }, onUse = { _, _ -> })
    }
}
