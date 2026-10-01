package io.github.iffix.neutrino.screen

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import io.github.iffix.neutrino.CLIENT_PERSON_CODES
import io.github.iffix.neutrino.channel.HubConnection
import io.github.iffix.neutrino.channel.HubNotice
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.design.ArmedButton
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
import io.github.iffix.neutrino.overlay.OverlayState

/**
 * The hubs this phone has joined, one row each with its state, its virtual network line and its
 * actions, then the row that opens the Join page.
 *
 * @param hubs Every hub joined.
 * @param notices The hubs that no longer know this phone, for a minute after their row went.
 * @param onJoin What pressing the join row does.
 * @param onLeave What the second press on Leave does, with the binding's id.
 * @param onReconnect What pressing Reconnect does, with the binding's id.
 * @param onOverlayConnect What pressing Connect on a hub's network does, with the binding's id.
 * @param onOverlayCancel What pressing Cancel does, with the binding's id.
 * @param onOverlayDisconnect What pressing Disconnect does, with the binding's id.
 * @param onOverlayPick What picking a network does, with the binding's id and the provider.
 */
@Composable
fun HubsScreen(
    hubs: List<HubView>,
    notices: List<HubNotice>,
    onJoin: () -> Unit,
    onLeave: (String) -> Unit,
    onReconnect: (String) -> Unit,
    onOverlayConnect: (String) -> Unit,
    onOverlayCancel: (String) -> Unit,
    onOverlayDisconnect: (String) -> Unit,
    onOverlayPick: (String, String) -> Unit,
) {
    val words = NeutrinoTheme.words
    val busyNetwork = hubs.firstOrNull { it.overlay.state != OverlayState.OFF }
    ScreenList {
        if (notices.isNotEmpty()) {
            cardRows(notices, key = { "notice-${it.hubTitle}-${it.refusal.code}" }) { notice, hasDivider ->
                FeatureRow(marker = DotTone.BAD, hasDivider = hasDivider) {
                    BasicText(words.word("ui.hub_forgot", mapOf("hub" to notice.hubTitle)), style = NeutrinoTheme.body)
                    ErrorLine(notice.refusal)
                }
            }
            gap()
        }
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
    hub.connection == HubConnection.DOWN && hub.lastError?.code in CLIENT_PERSON_CODES -> DotTone.BAD
    !hub.hasConnected && hub.connection != HubConnection.DISABLED -> DotTone.OFF
    else -> DotTone.WAIT
}

/**
 * The state word of a hub row: the running job's word, else the connection's.
 *
 * @param hub The hub.
 * @return The catalog key.
 */
fun hubStateKey(hub: HubView): String = when {
    hub.jobs.isLeaving -> "ui.job.leaving"
    hub.jobs.isRefreshing -> "ui.job.refreshing"
    else -> "ui.state.${hub.connection.wireName}"
}

@Composable
private fun HubRow(
    hub: HubView,
    otherNetwork: HubView?,
    hasDivider: Boolean,
    onLeave: (String) -> Unit,
    onReconnect: (String) -> Unit,
    onOverlayConnect: (String) -> Unit,
    onOverlayCancel: (String) -> Unit,
    onOverlayDisconnect: (String) -> Unit,
    onOverlayPick: (String, String) -> Unit,
) {
    val words = NeutrinoTheme.words
    val id = hub.binding.id
    val networks = hub.binding.overlays
    val line = hub.overlay
    val chosen = line.network.takeIf { line.state != OverlayState.OFF }
        ?: networks.firstOrNull { it.provider == hub.binding.overlayChoice }?.provider
        ?: networks.firstOrNull()?.provider.orEmpty()
    val networkReason = when {
        line.state != OverlayState.OFF -> null

        hub.isDisabled -> words.word("ui.reason.disabled")

        networks.isEmpty() -> words.word("ui.reason.no_network")

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
            if (networks.size >= 2) {
                PickerField(
                    options = networks.map { it.provider to it.title },
                    selected = chosen,
                    onSelect = { onOverlayPick(id, it) },
                    head = words.word("ui.overlay_count", mapOf("count" to networks.size)),
                    isEnabled = line.state == OverlayState.OFF && !hub.isDisabled,
                    isWide = false,
                )
            }
            when {
                line.state == OverlayState.CONNECTING -> NeutrinoButton(
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
            if (hub.connection == HubConnection.REPLACED) {
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
        BasicText(hub.binding.title, style = NeutrinoTheme.rowTitle)
        BasicText(words.word(hubStateKey(hub)), style = NeutrinoTheme.note)
        val software = if (hub.software.isEmpty()) {
            ""
        } else {
            " · " + words.word("ui.hub_software", mapOf("software" to hub.software))
        }
        BasicText(hub.connectedAddress.ifEmpty { hub.binding.gatewayUrl } + software, style = NeutrinoTheme.mono)
        ErrorLine(hub.jobError ?: hub.lastError?.takeIf { !hub.jobs.isRefreshing })
        Row(
            modifier = Modifier.padding(top = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            StatusDot(
                when (line.state) {
                    OverlayState.ON -> if (line.job == OverlayJob.NONE) DotTone.OK else DotTone.PULSE
                    OverlayState.CONNECTING -> DotTone.PULSE
                    OverlayState.OFF -> DotTone.OFF
                },
            )
            val state = words.word("ui.overlay.${line.state.wireName}", mapOf("address" to line.address))
            val engine = if (networks.size == 1) " · " + networks.first().title else ""
            BasicText(words.word("ui.overlay") + " · " + state + engine, style = NeutrinoTheme.note)
        }
        ErrorLine(line.error)
        ReasonLine(networkReason ?: words.word("ui.reason.disabled").takeIf { hub.isDisabled })
    }
}

@Preview(widthDp = 400, heightDp = 700)
@Composable
private fun HubsScreenPreview() {
    PreviewHubs.Frame(
        mapOf(
            "ui.state.connected" to "已连接",
            "ui.state.down" to "未连上",
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
            emptyList(),
            onJoin = {},
            onLeave = {},
            onReconnect = {},
            onOverlayConnect = {},
            onOverlayCancel = {},
            onOverlayDisconnect = {},
            onOverlayPick = { _, _ -> },
        )
    }
}
