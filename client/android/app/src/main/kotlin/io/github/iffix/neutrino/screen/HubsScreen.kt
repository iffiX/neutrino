package io.github.iffix.neutrino.screen

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.HubConnection
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.design.AppIcon
import io.github.iffix.neutrino.design.ButtonTier
import io.github.iffix.neutrino.design.DotTone
import io.github.iffix.neutrino.design.FeatureRow
import io.github.iffix.neutrino.design.NeutrinoButton
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.design.PlaceholderFrame
import io.github.iffix.neutrino.design.ScreenColumn
import io.github.iffix.neutrino.design.SurfaceCard
import kotlinx.coroutines.launch

/**
 * The hubs this phone has joined, each with where its socket stands and the way to leave it,
 * and the way to join another.
 *
 * @param hubs Every hub joined.
 * @param onJoin What pressing Join a hub does.
 * @param onLeave What confirming a leave does, with the binding's id.
 * @param onReconnect What pressing Reconnect does, with the binding's id.
 * @param overlayLine What a hub row shows under its lines for its virtual network, or nothing.
 */
@Composable
fun HubsScreen(
    hubs: List<HubView>,
    onJoin: () -> Unit,
    onLeave: suspend (String) -> ChannelResult<Unit>,
    onReconnect: (String) -> Unit,
    overlayLine: @Composable (HubView) -> Unit = {},
) {
    val words = NeutrinoTheme.words
    ScreenColumn {
        if (hubs.isEmpty()) {
            PlaceholderFrame(
                line = words.word("ui.no_hubs"),
                hint = words.word("ui.join_hint"),
                action = {
                    NeutrinoButton(words.word("ui.add_hub"), onJoin, tier = ButtonTier.PRIMARY, icon = AppIcon.PLUS)
                },
            )
            return@ScreenColumn
        }
        SurfaceCard {
            hubs.forEachIndexed { index, hub ->
                HubRow(hub, index < hubs.lastIndex, onLeave, onReconnect, overlayLine)
            }
        }
        NeutrinoButton(words.word("ui.add_hub"), onJoin, icon = AppIcon.PLUS, isWide = true)
    }
}

@Composable
private fun HubRow(
    hub: HubView,
    hasDivider: Boolean,
    onLeave: suspend (String) -> ChannelResult<Unit>,
    onReconnect: (String) -> Unit,
    overlayLine: @Composable (HubView) -> Unit,
) {
    val words = NeutrinoTheme.words
    val palette = NeutrinoTheme.palette
    val scope = rememberCoroutineScope()
    var isAsking by remember { mutableStateOf(false) }
    var isLeaving by remember { mutableStateOf(false) }
    var leaveError by remember { mutableStateOf<ChannelResult.Refused?>(null) }
    val title = hub.binding.title
    FeatureRow(
        marker = when (hub.connection) {
            HubConnection.CONNECTED -> DotTone.OK
            HubConnection.REPLACED, HubConnection.UNBOUND -> DotTone.OFF
            else -> DotTone.WAIT
        },
        hasDivider = hasDivider,
        trailing = if (isAsking) {
            null
        } else {
            {
                NeutrinoButton(words.word("ui.disconnect"), {
                    isAsking = true
                }, tier = ButtonTier.DANGER, isSmall = true)
            }
        },
    ) {
        BasicText(title, style = NeutrinoTheme.rowTitle)
        BasicText(words.word(stateKey(hub)), style = NeutrinoTheme.note)
        val software = if (hub.software.isEmpty()) {
            ""
        } else {
            " · " +
                words.word("ui.hub_software", mapOf("software" to hub.software))
        }
        BasicText(hub.binding.gatewayUrl + software, style = NeutrinoTheme.mono)
        val error = leaveError ?: hub.lastError?.takeIf { !hub.isConnected || hub.isDisabled }
        if (error != null) {
            BasicText(
                words.refusal(error.code, error.wordParams),
                style = NeutrinoTheme.note.copy(color = palette.warn),
            )
        }
        if (hub.connection == HubConnection.REPLACED) {
            Row(modifier = Modifier.padding(top = 8.dp)) {
                NeutrinoButton(words.word("ui.reconnect"), { onReconnect(hub.binding.id) }, isSmall = true)
            }
        }
        overlayLine(hub)
        if (isAsking) {
            val shape = RoundedCornerShape(10.dp)
            Column(
                modifier = Modifier
                    .padding(top = 8.dp)
                    .fillMaxWidth()
                    .clip(shape)
                    .background(palette.errorWash)
                    .border(1.dp, palette.error, shape)
                    .padding(12.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                BasicText(
                    words.word("ui.leave_confirm", mapOf("hub" to title)),
                    style = NeutrinoTheme.body.copy(color = palette.text),
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    NeutrinoButton(
                        words.word("ui.disconnect"),
                        {
                            isLeaving = true
                            scope.launch {
                                val answer = onLeave(hub.binding.id)
                                isLeaving = false
                                isAsking = false
                                leaveError = answer as? ChannelResult.Refused
                            }
                        },
                        tier = ButtonTier.DANGER,
                        isSmall = true,
                        isEnabled = !isLeaving,
                    )
                    NeutrinoButton(words.word("ui.cancel"), {
                        isAsking = false
                    }, tier = ButtonTier.GHOST, isSmall = true)
                }
            }
        }
    }
}

private fun stateKey(hub: HubView): String = when {
    hub.isDisabled -> "ui.disabled"
    hub.connection == HubConnection.CONNECTED -> "ui.connected"
    hub.connection == HubConnection.REPLACED -> "state.replaced"
    hub.connection == HubConnection.CONNECTING -> "ui.not_reached"
    else -> "ui.reconnecting"
}

@Preview(widthDp = 400, heightDp = 600)
@Composable
private fun HubsScreenPreview() {
    PreviewHubs.Frame(
        mapOf(
            "ui.connected" to "已连接",
            "ui.reconnecting" to "正在重新连接 hub",
            "ui.hub_software" to "运行 {software}",
            "ui.disconnect" to "离开",
            "ui.add_hub" to "加入 hub",
        ),
    ) { HubsScreen(PreviewHubs.all, onJoin = {}, onLeave = { ChannelResult.Ok(Unit) }, onReconnect = {}) }
}
