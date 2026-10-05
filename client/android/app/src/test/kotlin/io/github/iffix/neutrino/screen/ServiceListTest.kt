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
        mapOf("ui.machine_provided_by" to "由 {hub}:{device} 提供", "ui.module_ai_gateway" to "AI 网关"),
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
    fun anEntryOfAnotherMachineNamesTheHubAndTheMachine() {
        assertEquals("由 nmxhub:Argon 提供", providerLine(hub, entry("Argon"), "10.0.0.5", words))
        assertEquals("由 nmxhub:10.0.0.5 提供", providerLine(hub, entry(""), "10.0.0.5", words))
    }

    @Test
    fun anEntryTheHubsOwnMachineServesNamesTheHubOnce() {
        assertEquals("由 nmxhub:AI 网关 提供", providerLine(hub, entry("nmxhub", "ai_gateway"), "", words))
        assertEquals("由 nmxhub:Gitea 提供", providerLine(hub, entry("nmxhub", "gitea_module"), "", words))
        assertEquals(
            "由 nmxhub:whoami:latest 提供",
            providerLine(hub, entry("nmxhub", "container", image = "docker.io/traefik/whoami:latest"), "", words),
        )
        assertEquals("由 nmxhub:wiki 提供", providerLine(hub, entry("nmxhub", "declared", title = "wiki"), "", words))
    }
}
