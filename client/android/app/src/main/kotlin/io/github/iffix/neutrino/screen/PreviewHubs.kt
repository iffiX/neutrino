package io.github.iffix.neutrino.screen

import androidx.compose.runtime.Composable
import io.github.iffix.neutrino.binding.HubBinding
import io.github.iffix.neutrino.channel.ChannelApp
import io.github.iffix.neutrino.channel.ChannelOverlay
import io.github.iffix.neutrino.channel.ChannelServiceEntry
import io.github.iffix.neutrino.channel.ChannelTerminal
import io.github.iffix.neutrino.channel.HubConnection
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.channel.HubWaitReason
import io.github.iffix.neutrino.design.NeutrinoPalette
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.words.WordCatalog
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** Sample hubs the screens' previews draw: one connected with a service of each type, one down. */
object PreviewHubs {
    private fun payload(vararg fields: Pair<String, Any>) = JsonObject(
        fields.associate { (name, value) ->
            name to when (value) {
                is Int -> JsonPrimitive(value)
                is Boolean -> JsonPrimitive(value)
                else -> JsonPrimitive(value.toString())
            }
        },
    )

    /** The connected hub. */
    val neutrino = HubView(
        binding = HubBinding(
            id = "b1",
            hubId = "h1",
            hubName = "Neutrino",
            gatewayUrl = "tcp://192.168.100.1:8443",
            token = "",
            overlays = listOf(
                ChannelOverlay(provider = "easytier", mode = "console", configServer = "tcp://c/t"),
            ),
        ),
        connection = HubConnection.CONNECTED,
        software = "neutrino_hub/0.5.0",
        services = listOf(
            ChannelServiceEntry(
                "gitea_d1_web",
                "web",
                "Gitea",
                payload("url" to "http://192.168.10.20:3000/"),
                deviceName = "Argon",
                appId = "gitea_d1",
                name = "web",
                localPort = 27311,
            ),
            ChannelServiceEntry(
                "gitea_d1_ssh",
                "port",
                "Gitea",
                payload("host" to "192.168.10.20", "port" to 2222),
                deviceName = "Argon",
                appId = "gitea_d1",
                name = "ssh",
                localPort = 30418,
            ),
            ChannelServiceEntry(
                "vscode_d1_iffi_web",
                "web",
                "VS Code (iffi)",
                payload("url" to "http://192.168.10.20:8000/", "is_token_required" to true),
                deviceName = "Argon",
                appId = "vscode_d1_iffi",
                name = "web",
                localPort = 25162,
            ),
            ChannelServiceEntry(
                "f1",
                "file",
                "public",
                payload("protocol" to "smb", "host" to "100.72.4.21", "share" to "public"),
                deviceName = "Argon",
            ),
        ),
        apps = listOf(
            ChannelApp("gitea_d1", "Gitea", "module", "d1", "Argon", "gitea.argon.localhost"),
            ChannelApp("vscode_d1_iffi", "VS Code (iffi)", "module", "d1", "Argon", "vs-code-iffi.argon.localhost"),
        ),
        terminals =
            listOf(
                ChannelTerminal("d1", "Argon", isOnline = true, accounts = listOf("iffi", "lab")),
                ChannelTerminal("d2", "Neutrino", isOnline = true, accounts = listOf("iffi")),
            ),
    )

    /** The hub that waits for its next round. */
    val lepton = HubView(
        binding = HubBinding(
            id = "b2",
            hubName = "lepton",
            gatewayUrl = "tcp://203.0.113.9:8443",
            token = "",
        ),
        connection = HubConnection.WAITING,
        waitReason = HubWaitReason.HUB_SILENT,
        nextRoundAtMillis = System.currentTimeMillis() + 5000,
        software = "neutrino_hub/0.5.0",
    )

    /** Both hubs. */
    val all = listOf(neutrino, lepton)

    /**
     * Draw a preview in the dark palette with the Chinese words the desktop client ships.
     *
     * @param words The sentences the preview needs.
     * @param content The screen.
     */
    @Composable
    fun Frame(words: Map<String, String>, content: @Composable () -> Unit) {
        NeutrinoTheme(NeutrinoPalette.dark, WordCatalog(words), content)
    }
}
