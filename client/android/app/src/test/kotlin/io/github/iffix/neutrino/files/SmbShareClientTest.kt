package io.github.iffix.neutrino.files

import io.github.iffix.neutrino.ConnectRefusedException
import io.github.iffix.neutrino.channel.ChannelFrames
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.FakeConnectHub
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.fail
import org.junit.Test

class SmbShareClientTest {
    private val root = ShareRoot(
        key = "b1~f1",
        title = "media",
        host = "192.0.2.5",
        share = "media",
        users = emptyList(),
        summary = "",
        bindingId = "b1",
        entryId = "f1",
    )
    private val login = ShareLogin("iffi", "secret")

    @Test
    fun everyConnectionIsAConnectStreamNamingTheRootsEntry() {
        val hub = FakeConnectHub(refusal = ChannelResult.refused("permission_denied", "kind" to "file"))
        val asked = mutableListOf<ShareRoot>()
        val client = SmbShareClient(5, 30, 5) { share ->
            asked += share
            hub.open(ChannelFrames.args("id" to share.entryId))
        }
        refusalOf { client.list(root, login, ShareDocumentId(root.key, "")) }
        assertEquals("f1", hub.opens.first()["id"]?.jsonPrimitive?.content)
        assertEquals(setOf(root), asked.toSet())
    }

    @Test
    fun aRefusalOfTheStreamIsTheHubsCode() {
        val hub = FakeConnectHub(refusal = ChannelResult.refused("permission_denied", "kind" to "file"))
        val client = SmbShareClient(5, 30, 5) { hub.open(ChannelFrames.args("id" to it.entryId)) }
        val error = refusalOf { client.list(root, login, ShareDocumentId(root.key, "")) }
        assertEquals("permission_denied", error.code)
        assertEquals("file", error.params["kind"]?.jsonPrimitive?.content)
    }

    @Test
    fun aHubThatIsNotConnectedIsItsCode() {
        val client = SmbShareClient(5, 30, 5) { ChannelResult.refused("hub_unreachable") }
        assertEquals("hub_unreachable", refusalOf { client.list(root, login, ShareDocumentId(root.key, "")) }.code)
    }

    private fun refusalOf(action: () -> Unit): ConnectRefusedException {
        try {
            action()
        } catch (error: ConnectRefusedException) {
            return error
        }
        fail("the share was reached")
        throw AssertionError()
    }
}
