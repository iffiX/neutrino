package io.github.iffix.neutrino.screen

import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.tooling.preview.Preview
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.design.DotTone
import io.github.iffix.neutrino.design.FeatureRow
import io.github.iffix.neutrino.design.NeutrinoButton
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.remotedesktop.RemoteDesktopTarget
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject

/**
 * The desktops the machines of the joined hubs share, each with Connect; a press takes the
 * address and seat password from the hub and opens the viewer.
 *
 * @param hubs Every hub joined.
 * @param material What the hub hands this phone for one entry: `{host, port, password}`.
 * @param onView What a connection with its material does: open the viewer.
 * @param onJoin What pressing Join a hub does.
 */
@Composable
fun RemoteDesktopScreen(
    hubs: List<HubView>,
    material: suspend (String, String) -> ChannelResult<JsonObject>,
    onView: (RemoteDesktopTarget) -> Unit,
    onJoin: () -> Unit,
) {
    val words = NeutrinoTheme.words
    val palette = NeutrinoTheme.palette
    val scope = rememberCoroutineScope()
    var working by remember { mutableStateOf("") }
    val notes = remember { mutableStateMapOf<String, ChannelResult.Refused>() }
    ServiceList(hubs, "rdp", "ui.empty_desktops", onJoin) { hub, entry, hasDivider ->
        val key = hub.binding.id + "/" + entry.id
        val host = entry.text("host")
        val isHealthy = entry.isHealthy != false
        val connect = {
            working = key
            notes.remove(key)
            scope.launch {
                val name = hub.binding.title + ":" + entry.deviceName.ifEmpty { entry.title }
                when (val target = RemoteDesktopTarget.of(name, material(hub.binding.id, entry.id))) {
                    is ChannelResult.Refused -> notes[key] = target
                    is ChannelResult.Ok -> onView(target.value)
                }
                working = ""
            }
            Unit
        }
        FeatureRow(
            marker = if (isHealthy) DotTone.OK else DotTone.OFF,
            isGreyed = !isHealthy,
            hasDivider = hasDivider,
            trailing = {
                NeutrinoButton(
                    label = words.word(if (working == key) "ui.rdp_connecting" else "ui.rdp_connect"),
                    onClick = connect,
                    isEnabled = working.isEmpty() && isHealthy,
                    isSmall = true,
                )
            },
        ) {
            BasicText(entry.title, style = NeutrinoTheme.rowTitle)
            BasicText("$host:${entry.number("port") ?: ""}", style = NeutrinoTheme.mono)
            BasicText(providedBy(hub, entry, host), style = NeutrinoTheme.note)
            if (!isHealthy) BasicText(words.word("ui.unhealthy"), style = NeutrinoTheme.note)
            notes[key]?.let { note ->
                BasicText(
                    words.refusal(note.code, note.wordParams),
                    style = NeutrinoTheme.note.copy(color = palette.error),
                )
            }
        }
    }
}

@Preview(widthDp = 400, heightDp = 600)
@Composable
private fun RemoteDesktopScreenPreview() {
    PreviewHubs.Frame(
        mapOf(
            "ui.machine_provided_by" to "由 {hub}:{device} 提供",
            "ui.rdp_connect" to "连接",
            "ui.unhealthy" to "当前无法访问",
            "ui.reconnecting" to "正在重新连接 hub",
        ),
    ) {
        RemoteDesktopScreen(
            PreviewHubs.all,
            material = { _, _ -> ChannelResult.refused("rdp_not_shared") },
            onView = {},
            onJoin = {},
        )
    }
}
