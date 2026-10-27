package io.github.iffix.neutrino.screen

import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import io.github.iffix.neutrino.FORWARD_BIND_HOST
import io.github.iffix.neutrino.channel.ChannelApp
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.ChannelServiceEntry
import io.github.iffix.neutrino.channel.HubView
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
import io.github.iffix.neutrino.words.WordCatalog
import java.net.URI
import java.net.URISyntaxException

/**
 * The apps the joined hubs publish, one row each: the title, the hub, the machine and the source,
 * and one mono line per `web` and `port` entry with its fixed local address; the machine's SSH server
 * is no app and has no row. Use starts the app's forwards and Stop takes its place while the app is in use;
 * Configure opens the local port dialog while the app is not in use; Open, shown while an app with
 * an `http` or `https` entry is in use, opens the browser there.
 *
 * @param hubs Every hub joined.
 * @param forwards Each app's row, by key `<binding>/<app>`.
 * @param portOf The local port an entry listens on, the person's or the hub's, by binding id and entry.
 * @param onUse What pressing Use does, with the binding id and the app id.
 * @param onOpen What pressing Open does, with the binding id and the app id.
 */
@Composable
fun AppsScreen(
    hubs: List<HubView>,
    forwards: Map<String, PortForwardRow>,
    portOf: (String, ChannelServiceEntry) -> Int,
    onUse: (String, String) -> Unit,
    onOpen: (String, String) -> Unit,
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
                    onOpen = { onOpen(hub.binding.id, app.id) },
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
    onOpen: () -> Unit,
    onConfigure: () -> Unit,
    onStop: () -> Unit,
) {
    val words = NeutrinoTheme.words
    val entries = entriesOf(hub, app)
    val job = row.job
    val isUsable = entries.any { it.isHealthy != false }
    val isFree = job == null && !hub.jobs.isRefreshing
    val hasPage = PortForwards.pageOf(entries) != null
    FeatureRow(
        marker = appTone(hub, entries, job != null),
        hasDivider = hasDivider,
        actions = {
            if (row.isInUse || job == PortForwardJob.DISCONNECTING) {
                NeutrinoButton(
                    words.word(if (job == PortForwardJob.DISCONNECTING) job.wordKey else "ui.app.stop"),
                    onStop,
                    tier = if (job == null) ButtonTier.DANGER else ButtonTier.PLAIN,
                    isSmall = true,
                    isBusy = job == PortForwardJob.DISCONNECTING,
                    isEnabled = job == null,
                )
            } else {
                NeutrinoButton(
                    words.word(if (job == PortForwardJob.OPENING) job.wordKey else "ui.app.use"),
                    onUse,
                    tier = ButtonTier.PRIMARY,
                    isSmall = true,
                    isBusy = job == PortForwardJob.OPENING,
                    isEnabled = isFree && isUsable && !hub.isDisabled,
                )
            }
            NeutrinoButton(
                words.word("ui.app.configure"),
                onConfigure,
                isSmall = true,
                isEnabled = isFree && !row.isInUse,
            )
            if (hasPage && row.isInUse) {
                NeutrinoButton(
                    words.word(if (job == PortForwardJob.OPENING) job.wordKey else "ui.app.open"),
                    onOpen,
                    isSmall = true,
                    isBusy = job == PortForwardJob.OPENING,
                    isEnabled = job == null,
                )
            }
        },
    ) {
        BasicText(app.title, style = NeutrinoTheme.rowTitle)
        BasicText(appProviderLine(hub, app, entries, words), style = NeutrinoTheme.note)
        for (entry in entries) {
            BasicText(entryLineOf(app, entry, portOf(hub.binding.id, entry), words), style = NeutrinoTheme.mono)
        }
        ErrorLine(row.error)
        if (isFree) ReasonLine(appReasonKey(hub, entries, row)?.let { words.word(it) })
    }
}

/**
 * An app's `web` and `port` entries, in the hub's order. No Apps page shows an `ssh` entry, so the machine's SSH
 * server, whose entries are all `ssh` ones, has no row.
 *
 * @param hub The hub that publishes the app.
 * @param app The app.
 * @return The entries.
 */
internal fun entriesOf(hub: HubView, app: ChannelApp): List<ChannelServiceEntry> =
    hub.services.filter { it.appId == app.id && (it.type == "web" || it.type == "port") }

/**
 * An entry's local address as the Apps page shows it: `<scheme>://<local name>:<port><path>` for a
 * `web` entry, `127.0.0.1:<port>` for a `port` entry with `/udp` after a UDP one.
 *
 * @param app The app, whose local name a web address carries.
 * @param entry The entry.
 * @param port The local port it listens on.
 * @param host The host the phone opens web pages under, or null for the app's own local name.
 * @return The address.
 */
internal fun localAddressOf(app: ChannelApp, entry: ChannelServiceEntry, port: Int, host: String? = null): String {
    if (entry.type == "web") {
        val name = host ?: app.localName.ifEmpty { FORWARD_BIND_HOST }
        val target = PortForwards.targetOf(entry.text("url"))
        if (target != null) return "${target.first}://$name:$port${target.second}"
    }
    return if (entry.protocol == "udp") "$FORWARD_BIND_HOST:$port/udp" else "$FORWARD_BIND_HOST:$port"
}

/**
 * An entry's mono line under its app: its local address, or its kind alone while it has no number,
 * and the health word while the hub reports it unhealthy.
 *
 * @param app The app, whose local name the address carries.
 * @param entry The entry.
 * @param port The local port it listens on.
 * @param words The catalog.
 * @return The line.
 */
internal fun entryLineOf(app: ChannelApp, entry: ChannelServiceEntry, port: Int, words: WordCatalog): String {
    val address = if (port > 0) localAddressOf(app, entry, port) else words.word("ui.entry_kind.${entry.type}")
    return if (entry.isHealthy == false) "$address · ${words.word("ui.unhealthy")}" else address
}

/** The sources an app's provider line words, as the hub names them. */
internal val APP_SOURCES = listOf("module", "declared", "manual")

/**
 * Which hub and which machine an app is on, and who answers for it: `ui.app_provided_by`, the
 * machine being the host its first entry points at when the hub names none.
 *
 * @param hub The hub that publishes the app.
 * @param app The app.
 * @param entries The app's entries.
 * @param words The catalog.
 * @return The line.
 */
internal fun appProviderLine(
    hub: HubView,
    app: ChannelApp,
    entries: List<ChannelServiceEntry>,
    words: WordCatalog,
): String {
    val source = if (app.source in APP_SOURCES) words.word("ui.app_source.${app.source}") else ""
    val machine = app.deviceName.ifEmpty { entries.firstOrNull()?.let(::entryHostOf).orEmpty() }
    return words.word("ui.app_provided_by", mapOf("hub" to hub.binding.title, "machine" to machine, "source" to source))
}

private fun entryHostOf(entry: ChannelServiceEntry): String {
    val url = entry.text("url")
    if (url.isEmpty()) return entry.text("host")
    val host = try {
        URI(url).host
    } catch (_: URISyntaxException) {
        null
    }
    return host?.trim('[', ']').orEmpty()
}

/**
 * Why an app's buttons are disabled.
 *
 * @param hub The hub that publishes the app.
 * @param entries The app's entries.
 * @param row The app's row.
 * @return `ui.reason.disabled` while the hub switched this phone off, `ui.reason.unhealthy` for Use
 *   while no entry is reachable and the app is not in use, else null; Configure is disabled while the
 *   app is in use with no line under it.
 */
internal fun appReasonKey(hub: HubView, entries: List<ChannelServiceEntry>, row: PortForwardRow): String? = when {
    hub.isDisabled -> "ui.reason.disabled"
    row.isInUse -> null
    entries.none { it.isHealthy != false } -> "ui.reason.unhealthy"
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
        AppsScreen(
            PreviewHubs.all,
            emptyMap(),
            portOf = { _, entry -> entry.localPort },
            onUse = { _, _ -> },
            onOpen = { _, _ -> },
        )
    }
}
