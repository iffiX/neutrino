package io.github.iffix.neutrino.screen

import io.github.iffix.neutrino.channel.ChannelServiceEntry
import io.github.iffix.neutrino.channel.HubConnection
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.channel.Samples
import io.github.iffix.neutrino.words.WordCatalog
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Test

class ServiceListTest {
    private val words = WordCatalog(
        mapOf(
            "ui.provided_by" to "由 {hub}:{device}:{module} 提供",
            "ui.module_title.samba" to "文件共享",
            "ui.module_title.siyuan" to "思源笔记",
            "ui.module_title.remote_desktop" to "远程桌面",
        ),
    )
    private val hub = HubView(Samples.binding.copy(hubName = "nmxhub"), HubConnection.CONNECTED)

    private fun entry(device: String, code: String = "", title: String = "entry", image: String = "") =
        ChannelServiceEntry(
            id = "e1",
            type = "web",
            title = title,
            descriptionCode = code,
            descriptionParams = if (image.isEmpty()) {
                JsonObject(emptyMap())
            } else {
                JsonObject(mapOf("image" to JsonPrimitive(image)))
            },
            deviceName = device,
        )

    @Test
    fun everyEntryNamesItsHubItsMachineAndItsModulesTitle() {
        assertEquals("由 nmxhub:nmxhub:文件共享 提供", providerLine(hub, entry("nmxhub", "samba_module"), "", words))
        assertEquals("由 nmxhub:Argon:文件共享 提供", providerLine(hub, entry("Argon", "samba_module"), "", words))
        assertEquals("由 nmxhub:studio:远程桌面 提供", providerLine(hub, entry("studio", "device_share"), "", words))
        assertEquals("由 nmxhub:Argon:Gitea 提供", providerLine(hub, entry("Argon", "gitea_module"), "", words))
        assertEquals(
            "由 nmxhub:Argon:思源笔记 提供",
            providerLine(hub, entry("Argon", "siyuan_module", title = "SiYuan (alice)"), "", words),
        )
        assertEquals(
            "由 nmxhub:Argon:VS Code 提供",
            providerLine(hub, entry("Argon", "vscode_module", title = "VS Code (alice)"), "", words),
        )
        assertEquals(
            "由 nmxhub:nmxhub:whoami:latest 提供",
            providerLine(hub, entry("nmxhub", "container", image = "docker.io/traefik/whoami:latest"), "", words),
        )
    }

    @Test
    fun aMachineTheHubDoesNotNameIsTheEntrysAddressAndARecordIsNamedByItsTitle() {
        assertEquals(
            "由 nmxhub:10.0.0.5:wiki 提供",
            providerLine(hub, entry("", "declared", title = "wiki"), "10.0.0.5", words),
        )
    }
}
