package io.github.iffix.neutrino.files

import io.github.iffix.neutrino.ConnectRefusedException
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.transport.FakeTransport
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
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
    private val login = { ShareLogin("iffi", "secret") }

    private fun refusingHub() = FakeTransport().apply {
        serve = { _, end -> FakeTransport.refuse(end, "permission_denied", buildJsonObject { put("kind", "file") }) }
    }

    @Test
    fun everyConnectionIsAConnectStreamNamingTheRootsEntry() {
        val hub = refusingHub()
        val asked = mutableListOf<ShareRoot>()
        val client = SmbShareClient(5, 30, 5) { share ->
            asked += share
            hub.connect(share.entryId)
        }
        refusalOf { client.list(root, login, ShareDocumentId(root.key, "")) }
        assertEquals("f1", (hub.opens.first()["open"] as JsonObject)["id"]?.jsonPrimitive?.content)
        assertEquals(setOf(root), asked.toSet())
    }

    @Test
    fun aRefusalOfTheStreamIsTheHubsCode() {
        val hub = refusingHub()
        val client = SmbShareClient(5, 30, 5) { hub.connect(it.entryId) }
        val error = refusalOf { client.list(root, login, ShareDocumentId(root.key, "")) }
        assertEquals("permission_denied", error.code)
        assertEquals("file", error.params["kind"]?.jsonPrimitive?.content)
    }

    @Test
    fun aMachinesShareReadsTheHubsLoginOnlyAsAConnectionIsMade() {
        val hub = refusingHub()
        var reads = 0
        val client = SmbShareClient(5, 30, 5) { hub.connect(it.entryId) }
        refusalOf {
            client.list(root, {
                reads += 1
                ShareLogin("smb_iffi", "generated")
            }, ShareDocumentId(root.key, ""))
        }
        assertEquals(1, reads)
    }

    @Test
    fun aRefusedLoginEndsTheConnectBeforeAnyStream() {
        val hub = refusingHub()
        val client = SmbShareClient(5, 30, 5) { hub.connect(it.entryId) }
        val error = refusalOf {
            client.list(root, {
                throw ConnectRefusedException("vault_locked", JsonObject(emptyMap()))
            }, ShareDocumentId(root.key, ""))
        }
        assertEquals("vault_locked", error.code)
        assertEquals(0, hub.opens.size)
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
