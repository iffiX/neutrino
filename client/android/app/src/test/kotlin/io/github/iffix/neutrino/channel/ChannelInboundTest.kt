package io.github.iffix.neutrino.channel

import io.github.iffix.neutrino.GoldenSchema
import kotlinx.serialization.descriptors.SerialDescriptor
import kotlinx.serialization.descriptors.elementNames
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ChannelInboundTest {
    private fun names(descriptor: SerialDescriptor) = descriptor.elementNames.toSet()

    private fun decode(text: String): ChannelInbound = ChannelInbound.decode(Json.parseToJsonElement(text).jsonObject)

    @Test
    fun theStateReadsEverySectionTheGoldenNames() {
        assertEquals(GoldenSchema.properties("ChannelClientState"), names(ChannelClientState.serializer().descriptor))
    }

    @Test
    fun anEntryReadsEveryFieldTheGoldenNames() {
        assertEquals(GoldenSchema.properties("ChannelServiceEntry"), names(ChannelServiceEntry.serializer().descriptor))
    }

    @Test
    fun anOverlayReadsEveryFieldTheGoldenNames() {
        assertEquals(GoldenSchema.properties("ChannelOverlay"), names(ChannelOverlay.serializer().descriptor))
    }

    @Test
    fun anAppReadsEveryFieldTheGoldenNames() {
        assertEquals(GoldenSchema.properties("ChannelApp"), names(ChannelApp.serializer().descriptor))
    }

    @Test
    fun aTerminalReadsEveryFieldTheGoldenNames() {
        assertEquals(GoldenSchema.properties("ChannelTerminal"), names(ChannelTerminal.serializer().descriptor))
    }

    @Test
    fun aTerminalSessionReadsEveryFieldTheGoldenNames() {
        assertEquals(
            GoldenSchema.properties("ChannelTerminalSession"),
            names(ChannelTerminalSession.serializer().descriptor),
        )
    }

    @Test
    fun aWelcomeIsRead() {
        val text =
            """{"type":"welcome","protocol":3,"role":"hub","id":"h","name":"Neutrino","software":"neutrino_hub/0.5.0"}"""
        assertEquals(
            ChannelInbound.Welcome(3, "hub", "h", "Neutrino", "neutrino_hub/0.5.0"),
            decode(text),
        )
        assertTrue(
            GoldenSchema.problems(
                kotlinx.serialization.json.Json.parseToJsonElement(text.replace("\"type\":\"welcome\",", "")),
                "ChannelWelcome",
            ).isEmpty(),
        )
    }

    @Test
    fun aRefusalCarriesItsCodeAndParams() {
        val frame = decode("""{"type":"refused","code":"protocol_too_old","params":{"peer":2,"hub":3,"min":3}}""")
        val refusal = (frame as ChannelInbound.Refused).refusal
        assertEquals("protocol_too_old", refusal.code)
        assertEquals(mapOf("peer" to "2", "hub" to "3", "min" to "3"), refusal.wordParams)
    }

    @Test
    fun aStateKeepsOnlyUsableOverlaysAndCleanUrls() {
        val text = """
            {"type":"state","hash":"h2","is_disabled":false,
             "services":[{"id":"s","type":"web","title":"Gitea","payload":{"url":"http://x"},"source":"module","is_healthy":null,"extra":1}],
             "urls":["tcp://a:8443/","tcp://a:8443",""],
             "overlays":[{"provider":"netbird","setup_key":"K"},{"provider":"easytier","mode":"manual","network_name":"n"}],
             "terminals":[{"device_id":"d","name":"Argon","is_online":true}],
             "future_section":{}}
        """.trimIndent()
        val state = (decode(text) as ChannelInbound.State).state
        assertEquals("h2", state.hash)
        assertEquals(listOf("tcp://a:8443"), state.urls)
        assertEquals(listOf("netbird"), state.overlays.map { it.provider })
        assertEquals("http://x", state.services.single().text("url"))
        assertEquals(null, state.services.single().isHealthy)
        assertEquals("Argon", state.terminals.single().name)
    }

    @Test
    fun aStateNamesTheAddressOfEachPathThroughAServer() {
        val text = """
            {"type":"state","hash":"h3","urls":["tcp://203.0.113.5:18443","tcp://frp-cat.example.org:30443"],
             "ssh_relay_url":"tcp://203.0.113.5:18443","sakurafrp_url":"tcp://frp-cat.example.org:30443",
             "reached_through":"sakurafrp"}
        """.trimIndent()
        val state = (decode(text) as ChannelInbound.State).state
        assertEquals(
            mapOf(
                ChannelPath.SSH_RELAY to "tcp://203.0.113.5:18443",
                ChannelPath.SAKURAFRP to "tcp://frp-cat.example.org:30443",
                ChannelPath.OPENFRP to "",
            ),
            state.serverUrls,
        )
        assertEquals("sakurafrp", state.reachedThrough)
    }

    @Test
    fun aReplyIsItsRequestWithItsParamsOrItsRefusal() {
        val answer = decode("""{"type":"reply","request":"r1","code":"","params":{"token":"t"}}""")
        val ok = (answer as ChannelInbound.Reply).result as ChannelResult.Ok
        assertEquals("r1", answer.request)
        assertEquals("t", ok.value["token"]!!.jsonPrimitive.content)
        val refused = decode("""{"type":"reply","request":"r2","code":"vault_locked","params":{}}""")
        assertEquals("vault_locked", ((refused as ChannelInbound.Reply).result as ChannelResult.Refused).code)
        val body = Json.parseToJsonElement("""{"request":"r1","code":"","params":{"token":"t"}}""") as JsonObject
        assertEquals(emptyList<String>(), GoldenSchema.problems(body, "ChannelReply"))
    }

    @Test
    fun aStateReadsItsAppsAndEachEntrysAppAndLocalPort() {
        val state = (
            decode(
                """
                {"type":"state","hash":"h4",
                 "services":[{"id":"gitea_d1_ssh","type":"port","title":"Gitea","payload":{"host":"h","port":22,"protocol":"tcp"},
                              "source":"module","app_id":"gitea_d1","name":"ssh","local_port":30418}],
                 "apps":[{"id":"gitea_d1","title":"Gitea","source":"module","device_id":"d1","device_name":"lab",
                          "local_name":"gitea.lab.localhost"}],
                 "terminals":[{"device_id":"d1","name":"lab","accounts":["iffi"]}]}
                """.trimIndent(),
            ) as ChannelInbound.State
            ).state
        assertEquals("gitea.lab.localhost", state.apps.single().localName)
        assertEquals("gitea_d1", state.services.single().appId)
        assertEquals("ssh", state.services.single().name)
        assertEquals(30418, state.services.single().localPort)
        assertEquals("tcp", state.services.single().protocol)
        assertEquals(listOf("iffi"), state.terminals.single().accounts)
    }

    @Test
    fun aPongIsReadWithTheNonceItEchoesAndIsTheGoldensPong() {
        val text = """{"type":"pong","nonce":"n7"}"""
        assertEquals(ChannelInbound.Pong("n7"), decode(text))
        assertEquals(ChannelInbound.Pong(""), decode("""{"type":"pong"}"""))
        assertTrue(
            GoldenSchema.problems(
                kotlinx.serialization.json.Json.parseToJsonElement(text.replace("\"type\":\"pong\",", "")),
                "ChannelPong",
            ).isEmpty(),
        )
    }

    @Test
    fun anUnknownFrameIsReadAsUnknown() {
        assertEquals(ChannelInbound.Unknown("gossip"), decode("""{"type":"gossip"}"""))
    }
}
