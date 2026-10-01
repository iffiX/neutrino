package io.github.iffix.neutrino.screen

import androidx.compose.runtime.Composable
import io.github.iffix.neutrino.binding.HubBinding
import io.github.iffix.neutrino.channel.ChannelOverlay
import io.github.iffix.neutrino.channel.ChannelServiceEntry
import io.github.iffix.neutrino.channel.ChannelTerminal
import io.github.iffix.neutrino.channel.HubConnection
import io.github.iffix.neutrino.channel.HubView
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
            gatewayUrl = "https://192.168.100.1:8443",
            fingerprint = "",
            token = "",
            overlays = listOf(
                ChannelOverlay(provider = "netbird", setupKey = "k"),
                ChannelOverlay(provider = "easytier", mode = "console", configServer = "tcp://c/t"),
            ),
        ),
        connection = HubConnection.CONNECTED,
        software = "neutrino_hub/0.5.0",
        services = listOf(
            ChannelServiceEntry(
                "w1",
                "web",
                "Gitea",
                payload("url" to "https://git.neutrino.lan"),
                deviceName = "Argon",
            ),
            ChannelServiceEntry(
                "w2",
                "web",
                "Jellyfin",
                payload("url" to "http://100.72.4.1:8096"),
                deviceName = "Neutrino",
            ),
            ChannelServiceEntry(
                "w3",
                "web",
                "VS Code",
                payload("url" to "http://127.0.0.1:8000", "is_local_only" to true),
                deviceName = "Argon",
            ),
            ChannelServiceEntry(
                "p1",
                "port",
                "SSH",
                payload("host" to "100.72.4.21", "port" to 22),
                deviceName = "Argon",
            ),
            ChannelServiceEntry("p2", "port", "PostgreSQL", payload("host" to "100.72.4.1", "port" to 5432)),
            ChannelServiceEntry(
                "ai",
                "ai",
                "AI gateway",
                payload("endpoint" to "http://100.72.4.1:8317", "protocol" to "openai"),
                deviceName = "Neutrino",
            ),
            ChannelServiceEntry(
                "f1",
                "file",
                "public",
                payload("protocol" to "smb", "host" to "100.72.4.21", "share" to "public"),
                deviceName = "Argon",
            ),
        ),
        terminals = listOf(ChannelTerminal("d1", "Argon", true), ChannelTerminal("d2", "Neutrino", true)),
    )

    /** The hub that is down. */
    val lepton = HubView(
        binding = HubBinding(
            id = "b2",
            hubName = "lepton",
            gatewayUrl = "https://203.0.113.9:8443",
            fingerprint = "",
            token = "",
        ),
        connection = HubConnection.DOWN,
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
