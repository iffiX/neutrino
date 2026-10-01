package io.github.iffix.neutrino.files

import io.github.iffix.neutrino.channel.ChannelServiceEntry
import io.github.iffix.neutrino.channel.HubConnection
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.channel.Samples
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ShareRootTest {
    private fun entry(payload: String, type: String = "file") =
        ChannelServiceEntry("f1", type, "media", Json.parseToJsonElement(payload).jsonObject, deviceName = "Argon")

    private val hub = HubView(Samples.binding.copy(hubName = "Neutrino"), connection = HubConnection.CONNECTED)

    @Test
    fun anSmbEntryIsARootNamedByItsHubAndEntry() {
        val root = ShareRoot.of(
            hub,
            entry("""{"protocol":"smb","host":"10.0.0.5","share":"media","users":["iffi","guest"]}"""),
        )
        assertEquals(ShareRoot("b1~f1", "media", "10.0.0.5", "media", listOf("iffi", "guest"), "Neutrino:Argon"), root)
    }

    @Test
    fun anEntryWithoutUsersHasNone() {
        assertEquals(
            emptyList<String>(),
            ShareRoot.of(hub, entry("""{"protocol":"smb","host":"h","share":"s"}"""))?.users,
        )
    }

    @Test
    fun anotherProtocolOrAMissingFieldIsNoRoot() {
        assertNull(ShareRoot.of(hub, entry("""{"protocol":"nfs","host":"h","share":"s"}""")))
        assertNull(ShareRoot.of(hub, entry("""{"protocol":"smb","host":"h"}""")))
        assertNull(ShareRoot.of(hub, entry("""{"protocol":"smb","host":"h","share":"s"}""", type = "web")))
    }

    @Test
    fun onlyConnectedHubsPublishRoots() {
        val file = entry("""{"protocol":"smb","host":"h","share":"s"}""")
        val down = hub.copy(connection = HubConnection.DOWN, services = listOf(file))
        assertEquals(1, ShareRoot.all(listOf(hub.copy(services = listOf(file)), down)).size)
    }
}
