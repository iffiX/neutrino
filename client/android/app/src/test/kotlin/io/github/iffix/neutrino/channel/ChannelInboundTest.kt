package io.github.iffix.neutrino.channel

import io.github.iffix.neutrino.GoldenSchema
import kotlinx.serialization.descriptors.SerialDescriptor
import kotlinx.serialization.descriptors.elementNames
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ChannelInboundTest {
    private fun names(descriptor: SerialDescriptor) = descriptor.elementNames.toSet()

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
            ChannelInbound.decode(text),
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
        val frame = ChannelInbound.decode(
            """{"type":"refused","code":"protocol_too_old","params":{"peer":2,"hub":3,"min":3}}""",
        )
        val refusal = (frame as ChannelInbound.Refused).refusal
        assertEquals("protocol_too_old", refusal.code)
        assertEquals(mapOf("peer" to "2", "hub" to "3", "min" to "3"), refusal.wordParams)
    }

    @Test
    fun aStateKeepsOnlyUsableOverlaysAndCleanUrls() {
        val text = """
            {"type":"state","hash":"h2","is_disabled":false,
             "services":[{"id":"s","type":"web","title":"Gitea","payload":{"url":"http://x"},"source":"module","is_healthy":null,"extra":1}],
             "urls":["https://a:8443/","https://a:8443",""],
             "overlays":[{"provider":"netbird","setup_key":"K"},{"provider":"easytier","mode":"manual","network_name":"n"}],
             "terminals":[{"device_id":"d","name":"Argon","is_online":true}],
             "future_section":{}}
        """.trimIndent()
        val state = (ChannelInbound.decode(text) as ChannelInbound.State).state
        assertEquals("h2", state.hash)
        assertEquals(listOf("https://a:8443"), state.urls)
        assertEquals(listOf("netbird"), state.overlays.map { it.provider })
        assertEquals("http://x", state.services.single().text("url"))
        assertEquals(null, state.services.single().isHealthy)
        assertEquals("Argon", state.terminals.single().name)
    }

    @Test
    fun streamFramesAreRead() {
        assertEquals(ChannelInbound.Credit(3, 99), ChannelInbound.decode("""{"type":"credit","stream":3,"bytes":99}"""))
        assertEquals(
            ChannelInbound.Open(2, "shell"),
            ChannelInbound.decode("""{"type":"open","stream":2,"kind":"shell"}"""),
        )
        val close = ChannelInbound.decode("""{"type":"close","stream":1,"code":"","params":{"exit_code":0}}""")
        assertEquals(1, (close as ChannelInbound.Close).stream)
    }

    @Test
    fun anUnknownFrameIsReadAsUnknown() {
        assertEquals(ChannelInbound.Unknown("gossip"), ChannelInbound.decode("""{"type":"gossip"}"""))
    }

    @Test(expected = IllegalArgumentException::class)
    fun aFrameThatIsNotAnObjectIsRefused() {
        ChannelInbound.decode("[]")
    }

    @Test(expected = IllegalArgumentException::class)
    fun aCloseWithoutAStreamIsRefused() {
        ChannelInbound.decode("""{"type":"close","code":""}""")
    }
}
