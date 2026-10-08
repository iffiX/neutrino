package io.github.iffix.neutrino.screen

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import io.github.iffix.neutrino.CLIENT_REACHED_THROUGH
import io.github.iffix.neutrino.channel.ChannelOverlay
import io.github.iffix.neutrino.channel.HubConnection
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.channel.HubWaitReason
import io.github.iffix.neutrino.design.ArmedButton
import io.github.iffix.neutrino.design.Badge
import io.github.iffix.neutrino.design.ButtonTier
import io.github.iffix.neutrino.design.DotTone
import io.github.iffix.neutrino.design.ErrorLine
import io.github.iffix.neutrino.design.FeatureRow
import io.github.iffix.neutrino.design.NeutrinoButton
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.design.PickerField
import io.github.iffix.neutrino.design.ReasonLine
import io.github.iffix.neutrino.design.ScreenList
import io.github.iffix.neutrino.design.StatusDot
import io.github.iffix.neutrino.design.cardRows
import io.github.iffix.neutrino.design.gap
import io.github.iffix.neutrino.overlay.OverlayJob
import io.github.iffix.neutrino.overlay.OverlayLine
import io.github.iffix.neutrino.overlay.OverlayStage
import io.github.iffix.neutrino.overlay.OverlayState
import io.github.iffix.neutrino.words.WordCatalog
import kotlin.math.ceil
import kotlinx.coroutines.delay

/** The waiting reasons a person has to act on, drawn with a red dot. */
private val PERSON_REASONS =
    setOf(
        HubWaitReason.UNTRUSTED,
        HubWaitReason.UNKNOWN_DEVICE,
        HubWaitReason.TOO_OLD,
        HubWaitReason.JOIN_REFUSED,
    )

/**
 * The hubs this phone has joined, one row each with its state, its virtual network line and its
 * actions, then the row that opens the Join page.
 *
 * @param hubs Every hub joined.
 * @param onJoin What pressing the join row does.
 * @param onLeave What the second press on Leave does, with the binding's id.
 * @param onReconnect What pressing Reconnect does, with the binding's id.
 * @param onOpenPanel What pressing Panel does, with the binding's id.
 * @param onOverlayConnect What pressing Connect on a hub's network does, with the binding's id.
 * @param onOverlayCancel What pressing Cancel does, with the binding's id.
 * @param onOverlayDisconnect What pressing Disconnect does, with the binding's id.
 * @param onOverlayPick What picking a network does, with the binding's id and the provider.
 */
@Composable
fun HubsScreen(
    hubs: List<HubView>,
    onJoin: () -> Unit,
    onLeave: (String) -> Unit,
    onReconnect: (String) -> Unit,
    onOpenPanel: (String) -> Unit,
    onOverlayConnect: (String) -> Unit,
    onOverlayCancel: (String) -> Unit,
    onOverlayDisconnect: (String) -> Unit,
    onOverlayPick: (String, String) -> Unit,
) {
    val words = NeutrinoTheme.words
    val busyNetwork = hubs.firstOrNull { it.overlay.state != OverlayState.OFF }
    ScreenList {
        if (hubs.isEmpty()) {
            cardRows(listOf("none"), key = { it }) { _, _ ->
                FeatureRow(hasDivider = false) { BasicText(words.word("ui.no_hubs"), style = NeutrinoTheme.body) }
            }
        } else {
            cardRows(hubs, key = { it.binding.id }) { hub, hasDivider ->
                HubRow(
                    hub = hub,
                    otherNetwork = busyNetwork?.takeIf { it.binding.id != hub.binding.id },
                    hasDivider = hasDivider,
                    onLeave = onLeave,
                    onReconnect = onReconnect,
                    onOpenPanel = onOpenPanel,
                    onOverlayConnect = onOverlayConnect,
                    onOverlayCancel = onOverlayCancel,
                    onOverlayDisconnect = onOverlayDisconnect,
                    onOverlayPick = onOverlayPick,
                )
            }
        }
        gap()
        cardRows(listOf("join"), key = { it }) { _, _ ->
            FeatureRow(onClick = onJoin, hasDivider = false, hasChevron = true) {
                BasicText(words.word("ui.add_hub"), style = NeutrinoTheme.rowTitle)
                BasicText(words.word("ui.join_hint"), style = NeutrinoTheme.note)
            }
        }
    }
}

/**
 * The status dot of a hub row, by the client page's dot table.
 *
 * @param hub The hub.
 * @return The tone.
 */
fun hubTone(hub: HubView): DotTone = when {
    hub.jobs.isAnyRunning || hub.connection == HubConnection.CONNECTING -> DotTone.PULSE
    hub.connection == HubConnection.CONNECTED -> DotTone.OK
    hub.waitReason in PERSON_REASONS -> DotTone.BAD
    !hub.hasConnected && !hub.isDisabled -> DotTone.OFF
    else -> DotTone.WAIT
}

/**
 * The whole seconds left before a waiting hub's next round, rounded up.
 *
 * @param hub The hub.
 * @param nowMillis The time now, in the session's clock.
 * @return The seconds, 0 once the moment has come, or null while no countdown runs.
 */
fun secondsToNextRound(hub: HubView, nowMillis: Long): Long? {
    if (hub.connection != HubConnection.WAITING || hub.nextRoundAtMillis <= 0) return null
    return ceil((hub.nextRoundAtMillis - nowMillis).coerceAtLeast(0) / 1000.0).toLong()
}

/**
 * The state word of a hub row: the running job's word, else the connection's, else the reason it
 * waits for; a countdown that reached 0 reads as connecting.
 *
 * @param hub The hub.
 * @param nowMillis The time now, in the session's clock.
 * @return The catalog key.
 */
fun hubStateKey(hub: HubView, nowMillis: Long): String {
    val reason = hub.waitReason
    return when {
        hub.jobs.isLeaving -> "ui.job.leaving"
        hub.jobs.isRefreshing -> "ui.job.refreshing"
        hub.isConnected && hub.reachedThrough in CLIENT_REACHED_THROUGH -> "ui.state.connected_through"
        hub.connection != HubConnection.WAITING || reason == null -> "ui.state.${hub.connection.wireName}"
        secondsToNextRound(hub, nowMillis) == 0L -> "ui.state.connecting"
        else -> "ui.state.${reason.wireName}"
    }
}

/**
 * The state word of a hub row, worded: `Connected · <way>` names the way the socket reached the hub.
 *
 * @param hub The hub.
 * @param words The catalog.
 * @param nowMillis The time now, in the session's clock.
 * @return The sentence.
 */
fun hubStateWord(hub: HubView, words: WordCatalog, nowMillis: Long): String =
    words.word(hubStateKey(hub, nowMillis), mapOf("way" to words.word("ui.through.${hub.reachedThrough}")))

/**
 * The state line of a hub row: the state word, then ` · ` and what ends the wait when the row
 * waits for one: the seconds left, the refusal's wording, or the Reconnect button's name.
 *
 * @param hub The hub.
 * @param words The catalog.
 * @param nowMillis The time now, in the session's clock.
 * @return The sentence.
 */
fun hubStateLine(hub: HubView, words: WordCatalog, nowMillis: Long): String {
    val word = hubStateWord(hub, words, nowMillis)
    if (hubStateKey(hub, nowMillis) != "ui.state.${hub.waitReason?.wireName}") return word
    val refusal = hub.waitRefusal
    val action = when {
        hub.nextRoundAtMillis > 0 ->
            words.word("ui.action.retry_in", mapOf("s" to secondsToNextRound(hub, nowMillis)))

        hub.waitReason == HubWaitReason.JOIN_REFUSED && refusal != null ->
            words.refusal(refusal.code, refusal.wordParams)

        hub.waitReason == HubWaitReason.REPLACED -> words.word("ui.reconnect")

        else -> null
    }
    return listOfNotNull(word, action).joinToString(" · ")
}

/**
 * The tags of a connected hub row with no job running: the state word with the way the socket
 * reached the hub, then the last round trip once a pong measured it.
 *
 * @param hub The hub.
 * @param words The catalog.
 * @return The tags, empty unless the row is connected and idle.
 */
fun hubTags(hub: HubView, words: WordCatalog): List<String> {
    if (!hub.isConnected || hub.jobs.isLeaving || hub.jobs.isRefreshing) return emptyList()
    val rtt = hub.rttMs?.let { words.word("ui.state.rtt", mapOf("ms" to it)) }
    return listOfNotNull(hubStateWord(hub, words, 0), rtt)
}

/**
 * Whether a hub row draws its virtual network line: a hub that publishes no network has none,
 * unless a network of its is still on or stopping.
 *
 * @param hub The hub.
 * @return True when the row shows the line, its button and its reason.
 */
fun hasNetworkLine(hub: HubView): Boolean = hub.binding.overlays.isNotEmpty() ||
    hub.overlay.state != OverlayState.OFF || hub.overlay.job != OverlayJob.NONE

/**
 * The state word of a hub's virtual network line: the connect's job word while it runs, else
 * `off` or `on` with the phone's address. The line names the engine and never the hub's channel.
 *
 * @param line The line.
 * @param words The catalog.
 * @return The sentence.
 */
fun overlayStateWord(line: OverlayLine, words: WordCatalog): String = if (line.job == OverlayJob.CONNECTING) {
    words.word("ui.job.connecting")
} else {
    words.word("ui.overlay.${line.state.wireName}", mapOf("address" to line.address))
}

@Composable
private fun HubRow(
    hub: HubView,
    otherNetwork: HubView?,
    hasDivider: Boolean,
    onLeave: (String) -> Unit,
    onReconnect: (String) -> Unit,
    onOpenPanel: (String) -> Unit,
    onOverlayConnect: (String) -> Unit,
    onOverlayCancel: (String) -> Unit,
    onOverlayDisconnect: (String) -> Unit,
    onOverlayPick: (String, String) -> Unit,
) {
    val words = NeutrinoTheme.words
    val id = hub.binding.id
    val networks = hub.binding.overlays
    val line = hub.overlay
    val chosen = line.network.takeIf { line.state != OverlayState.OFF || line.job != OverlayJob.NONE }
        ?: networks.firstOrNull { it.provider == hub.binding.overlayChoice }?.provider
        ?: networks.firstOrNull()?.provider.orEmpty()
    val networkReason = when {
        line.isWaiting -> words.word("ui.reason.console_waiting")

        line.job == OverlayJob.CONNECTING && line.stage == OverlayStage.LOGIN ->
            words.word("ui.stage.login", mapOf("engine" to ChannelOverlay(line.network).title))

        line.state != OverlayState.OFF || line.job != OverlayJob.NONE -> null

        hub.isDisabled -> words.word("ui.reason.disabled")

        otherNetwork != null -> words.refusal(
            "overlay_other_network",
            mapOf("network" to (networks.firstOrNull { it.provider == chosen }?.title ?: chosen)),
        )

        else -> null
    }
    FeatureRow(
        marker = hubTone(hub),
        hasDivider = hasDivider,
        actions = {
            if (networks.size >= 2 && !hub.isLeaveOnly) {
                PickerField(
                    options = networks.map { it.provider to it.title },
                    selected = chosen,
                    onSelect = { onOverlayPick(id, it) },
                    head = words.word("ui.overlay_count", mapOf("count" to networks.size)),
                    isEnabled = line.state == OverlayState.OFF && line.job == OverlayJob.NONE && !hub.isDisabled,
                    isWide = false,
                )
            }
            when {
                hub.isLeaveOnly || !hasNetworkLine(hub) -> Unit

                line.job == OverlayJob.CONNECTING -> NeutrinoButton(
                    words.word("ui.network_cancel"),
                    { onOverlayCancel(id) },
                    isSmall = true,
                    isBusy = true,
                    isEnabled = !hub.isDisabled,
                )

                line.job == OverlayJob.DISCONNECTING -> NeutrinoButton(
                    words.word("ui.job.disconnecting"),
                    {},
                    isSmall = true,
                    isBusy = true,
                    isEnabled = false,
                )

                line.state == OverlayState.ON -> NeutrinoButton(
                    words.word("ui.network_disconnect"),
                    { onOverlayDisconnect(id) },
                    isSmall = true,
                    isEnabled = !hub.isDisabled,
                )

                else -> NeutrinoButton(
                    words.word("ui.network_connect"),
                    { onOverlayConnect(id) },
                    isSmall = true,
                    isEnabled = networkReason == null,
                )
            }
            if (hub.isPanelAllowed && !hub.isLeaveOnly) {
                NeutrinoButton(
                    words.word(if (hub.jobs.isOpeningPanel) "ui.job.opening" else "ui.hub_panel"),
                    { onOpenPanel(id) },
                    isSmall = true,
                    isBusy = hub.jobs.isOpeningPanel,
                    isEnabled = hub.isConnected && !hub.jobs.isOpeningPanel && !hub.jobs.isLeaving,
                )
            }
            if (hub.waitReason == HubWaitReason.REPLACED) {
                NeutrinoButton(words.word("ui.reconnect"), { onReconnect(id) }, isSmall = true)
            }
            ArmedButton(
                key = "leave-$id",
                label = words.word(if (hub.jobs.isLeaving) "ui.job.leaving" else "ui.leave"),
                armedLabel = words.word("ui.leave_armed"),
                onAct = { onLeave(id) },
                isBusy = hub.jobs.isLeaving,
            )
        },
    ) {
        val tags = hubTags(hub, words)
        val nowMillis by produceState(System.currentTimeMillis(), hub.nextRoundAtMillis) {
            while (true) {
                value = System.currentTimeMillis()
                val leftMillis = hub.nextRoundAtMillis - value
                if (leftMillis <= 0) break
                delay((leftMillis - 1) % 1000 + 1)
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            BasicText(hub.binding.title, style = NeutrinoTheme.rowTitle)
            tags.forEach { Badge(it) }
        }
        if (tags.isEmpty()) BasicText(hubStateLine(hub, words, nowMillis), style = NeutrinoTheme.note)
        val software = if (hub.software.isEmpty()) {
            ""
        } else {
            " · " + words.word("ui.hub_software", mapOf("software" to hub.software))
        }
        BasicText(hub.connectedAddress.ifEmpty { hub.binding.gatewayUrl } + software, style = NeutrinoTheme.mono)
        ErrorLine(hub.jobError)
        if (hasNetworkLine(hub)) {
            NetworkLine(hub, networkReason)
        } else {
            ReasonLine(words.word("ui.reason.disabled").takeIf { hub.isDisabled })
        }
    }
}

@Composable
private fun NetworkLine(hub: HubView, networkReason: String?) {
    val words = NeutrinoTheme.words
    val networks = hub.binding.overlays
    val line = hub.overlay
    Row(
        modifier = Modifier.padding(top = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        StatusDot(
            when {
                line.job != OverlayJob.NONE -> DotTone.PULSE
                line.state == OverlayState.ON -> DotTone.OK
                else -> DotTone.OFF
            },
        )
        val state = overlayStateWord(line, words)
        val engine = if (networks.size == 1) " · " + networks.first().title else ""
        BasicText(words.word("ui.overlay") + " · " + state + engine, style = NeutrinoTheme.note)
    }
    ErrorLine(line.error)
    ReasonLine(networkReason ?: words.word("ui.reason.disabled").takeIf { hub.isDisabled })
}

@Preview(widthDp = 400, heightDp = 700)
@Composable
private fun HubsScreenPreview() {
    PreviewHubs.Frame(
        mapOf(
            "ui.state.connected" to "已连接",
            "ui.state.hub_silent" to "中枢未响应",
            "ui.action.retry_in" to "{s} 秒后重试",
            "ui.hub_software" to "运行 {software}",
            "ui.leave" to "离开",
            "ui.add_hub" to "加入 hub",
            "ui.network_connect" to "连接",
            "ui.overlay" to "虚拟网",
            "ui.overlay.off" to "未连接",
        ),
    ) {
        HubsScreen(
            PreviewHubs.all,
            onJoin = {},
            onLeave = {},
            onReconnect = {},
            onOpenPanel = {},
            onOverlayConnect = {},
            onOverlayCancel = {},
            onOverlayDisconnect = {},
            onOverlayPick = { _, _ -> },
        )
    }
}
