package io.github.iffix.neutrino.screen

import android.os.Build
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.tooling.preview.Preview
import io.github.iffix.neutrino.CLIENT_PLATFORM_OS_DARWIN
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.ChannelServiceEntry
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.design.ErrorLine
import io.github.iffix.neutrino.design.FeatureRow
import io.github.iffix.neutrino.design.NeutrinoButton
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.design.ReasonLine
import io.github.iffix.neutrino.remotedesktop.RemoteDesktopChoice
import io.github.iffix.neutrino.remotedesktop.RemoteDesktopCodec
import io.github.iffix.neutrino.remotedesktop.RemoteDesktopSessions
import io.github.iffix.neutrino.shell.LocalClientActions

/**
 * The desktops the machines of the joined hubs share, each with Connect: the button shows the
 * job while the address and seat password come from the hub, then the viewer opens. Configure,
 * at its left, keeps the codec and the quality the next Connect asks for. A Mac's entry carries a
 * standing hint that a black picture or a mouse that does nothing means RustDesk lacks its
 * permissions there.
 *
 * @param hubs Every hub joined.
 * @param connecting The entries whose Connect runs, by entry key.
 * @param errors The code each entry's last Connect ended in, by entry key.
 * @param viewingKey The entry the open viewer shows, or null.
 * @param dialed The address each entry's viewer dials, by entry key, once the hub handed it back;
 *   the row's mono line, absent until then.
 * @param onConnect What pressing Connect does, with the binding id, the entry id, the viewer's title
 *   and the entry's `platform_os`.
 */
@Composable
fun RemoteDesktopScreen(
    hubs: List<HubView>,
    connecting: Set<String>,
    errors: Map<String, ChannelResult.Refused>,
    viewingKey: String?,
    dialed: Map<String, String>,
    onConnect: (String, String, String, String) -> Unit,
) {
    val words = NeutrinoTheme.words
    val actions = LocalClientActions.current
    var configuring by remember { mutableStateOf<Triple<String, String, String>?>(null) }
    ServiceList(hubs, "rdp", "ui.empty_desktops") { hub, entry, hasDivider ->
        val key = RemoteDesktopSessions.keyOf(hub.binding.id, entry.id)
        val host = entry.text("host")
        val isHealthy = entry.isHealthy != false
        val isBusy = key in connecting
        val reason = when {
            !isHealthy -> entry.descriptionCode.takeIf { it.isNotEmpty() }?.let { words.refusal(it) }
                ?: words.word("ui.reason.unhealthy")

            viewingKey != null -> words.word("ui.reason_viewer_open")

            else -> null
        }
        FeatureRow(
            marker = entryTone(hub, entry, isBusy),
            hasDivider = hasDivider,
            actions = {
                NeutrinoButton(
                    label = words.word("ui.configure"),
                    onClick = { configuring = Triple(hub.binding.id, entry.id, entry.title) },
                    isEnabled = isHealthy && !hub.jobs.isRefreshing,
                    isSmall = true,
                )
                NeutrinoButton(
                    label = words.word(if (isBusy) "ui.job.connecting" else "ui.rdp_connect"),
                    onClick = {
                        val name = hub.binding.title + ":" + entry.deviceName.ifEmpty { entry.title }
                        onConnect(hub.binding.id, entry.id, name, entry.text("platform_os"))
                    },
                    isEnabled = reason == null && !isBusy && !hub.jobs.isRefreshing,
                    isBusy = isBusy,
                    isSmall = true,
                )
            },
        ) {
            BasicText(entry.title, style = NeutrinoTheme.rowTitle)
            if (viewingKey == key) BasicText(words.word("ui.rdp_open"), style = NeutrinoTheme.note)
            dialed[key]?.let { BasicText(it, style = NeutrinoTheme.mono) }
            BasicText(providedBy(hub, entry, host), style = NeutrinoTheme.note)
            if (hasMacHint(entry)) BasicText(words.word("ui.rdp_mac_hint"), style = NeutrinoTheme.note)
            ErrorLine(errors[key])
            ReasonLine(reason)
        }
    }
    configuring?.let { (bindingId, entryId, title) ->
        RemoteDesktopDialog(
            title = title,
            codecs = RemoteDesktopCodec.offered(Build.SUPPORTED_ABIS.firstOrNull().orEmpty()),
            initial = remember(bindingId, entryId) {
                actions?.remoteDesktopChoiceOf(bindingId, entryId) ?: RemoteDesktopChoice()
            },
            onSave = { actions?.configureRemoteDesktop(bindingId, entryId, it) },
            onClose = { configuring = null },
        )
    }
}

/**
 * Whether a desktop entry carries the standing Mac hint under its provider line.
 *
 * @param entry The desktop entry.
 * @return True when the sharing machine is a Mac.
 */
internal fun hasMacHint(entry: ChannelServiceEntry): Boolean = entry.text("platform_os") == CLIENT_PLATFORM_OS_DARWIN

@Preview(widthDp = 400, heightDp = 600)
@Composable
private fun RemoteDesktopScreenPreview() {
    PreviewHubs.Frame(
        mapOf(
            "ui.machine_provided_by" to "由 {hub}:{device} 提供",
            "ui.rdp_connect" to "连接",
            "ui.unhealthy" to "当前无法访问",
        ),
    ) {
        RemoteDesktopScreen(PreviewHubs.all, emptySet(), emptyMap(), null, emptyMap(), onConnect = { _, _, _, _ -> })
    }
}
