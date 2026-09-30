package io.github.iffix.neutrino.channel

import io.github.iffix.neutrino.GoldenSchema
import io.github.iffix.neutrino.binding.BindingStore
import io.github.iffix.neutrino.binding.FakeSecretSealer
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class HubConnectionsTest {
    @get:Rule
    val folder = TemporaryFolder()

    private val link = (EnrollmentLink.parse(Samples.link(Samples.clientPayload)) as ChannelResult.Ok).value
    private val transport = FakeHubTransport { FakeHubTransport.silent }

    private fun TestScope.connections(): Pair<HubConnections, BindingStore> {
        val store = BindingStore(folder.root.resolve("b.sealed"), FakeSecretSealer())
        return HubConnections(store, transport, Samples.machine, { null }, backgroundScope) to store
    }

    private fun joined() =
        ChannelResult.Ok(JsonObject(mapOf("id" to JsonPrimitive("b9"), "token" to JsonPrimitive("t9"))))

    @Test
    fun joiningTriesEachAddressUntilOneAnswersAndKeepsTheBinding() = runTest {
        val (connections, store) = connections()
        transport.answers["https://100.72.4.1:8443" to "/api/channel/join"] = joined()
        val binding = (connections.join(link) as ChannelResult.Ok).value
        assertEquals(listOf("https://192.168.100.1:8443", "https://100.72.4.1:8443"), transport.posts.map { it.first })
        assertEquals("https://100.72.4.1:8443", binding.gatewayUrl)
        assertEquals(link.urls, binding.gatewayUrls)
        assertEquals(listOf("netbird", "easytier"), binding.overlays.map { it.provider })
        assertEquals(binding, store.get("b9"))
    }

    @Test
    fun theJoinBodyIsTheGoldens() = runTest {
        val (connections, _) = connections()
        connections.join(link)
        assertEquals(emptyList<String>(), GoldenSchema.problems(transport.posts.first().third, "ChannelJoinRequest"))
    }

    @Test
    fun aProtocolRefusalIsReturnedAsItIs() = runTest {
        val (connections, _) = connections()
        transport.answers["https://192.168.100.1:8443" to "/api/channel/join"] =
            ChannelResult.refused("protocol_too_old", "peer" to "3")
        assertEquals("protocol_too_old", (connections.join(link) as ChannelResult.Refused).code)
    }

    @Test
    fun aSpentTicketIsEnrollRefused() = runTest {
        val (connections, _) = connections()
        transport.answers["https://192.168.100.1:8443" to "/api/channel/join"] = ChannelResult.refused("ticket_spent")
        assertEquals("enroll_refused", (connections.join(link) as ChannelResult.Refused).code)
    }

    @Test
    fun anotherCertificateStopsTheJoin() = runTest {
        val (connections, _) = connections()
        transport.answers["https://192.168.100.1:8443" to "/api/channel/join"] =
            ChannelResult.refused("hub_untrusted", "url" to "x")
        assertEquals("hub_untrusted", (connections.join(link) as ChannelResult.Refused).code)
        assertEquals(1, transport.posts.size)
    }

    @Test
    fun anAnswerWithoutATokenIsEnrollNoToken() = runTest {
        val (connections, _) = connections()
        transport.answers["https://192.168.100.1:8443" to "/api/channel/join"] =
            ChannelResult.Ok(JsonObject(emptyMap()))
        assertEquals("enroll_no_token", (connections.join(link) as ChannelResult.Refused).code)
    }

    @Test
    fun noAddressAnsweringIsUnreachableNamingThem() = runTest {
        val (connections, _) = connections()
        val refusal = connections.join(link) as ChannelResult.Refused
        assertEquals("hub_unreachable", refusal.code)
        assertEquals(link.urls.joinToString(", "), refusal.wordParams["urls"])
    }

    @Test
    fun leavingForgetsTheBindingOnceTheHubAgreesOrNoLongerKnowsIt() = runTest {
        val (connections, store) = connections()
        store.put(Samples.binding)
        transport.answers["https://192.168.100.1:8443" to "/api/channel/leave"] =
            ChannelResult.refused("binding_unknown")
        assertEquals(ChannelResult.Ok(Unit), connections.leave("b1"))
        assertNull(store.get("b1"))
        assertEquals(emptyList<String>(), GoldenSchema.problems(transport.posts.single().third, "ChannelLeaveRequest"))
    }

    @Test
    fun anUnreachableHubKeepsTheBinding() = runTest {
        val (connections, store) = connections()
        store.put(Samples.binding)
        assertEquals("hub_unreachable", (connections.leave("b1") as ChannelResult.Refused).code)
        assertEquals(Samples.binding, store.get("b1"))
    }
}
