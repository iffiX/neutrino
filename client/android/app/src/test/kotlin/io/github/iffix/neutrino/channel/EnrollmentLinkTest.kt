package io.github.iffix.neutrino.channel

import java.util.Base64
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Test

class EnrollmentLinkTest {
    private fun refusalOf(text: String) = (EnrollmentLink.parse(text) as ChannelResult.Refused).code

    @Test
    fun aClientLinkIsRead() {
        val link = (EnrollmentLink.parse(Samples.link(Samples.clientPayload)) as ChannelResult.Ok).value
        assertEquals(listOf("https://192.168.100.1:8443", "https://100.72.4.1:8443"), link.urls)
        assertEquals("ticket-1", link.ticket)
        assertEquals(Samples.FINGERPRINT, link.fingerprint)
        assertEquals(Samples.clientProviders, link.overlays.map { it.provider })
        assertEquals("console", link.overlays.last().easyTierMode)
    }

    @Test
    fun theBarePayloadAndThePaddedFormAreRead() {
        val bare = Samples.link(Samples.clientPayload).removePrefix("neutrino://enroll/")
        assertEquals(true, EnrollmentLink.parse("  $bare\n") is ChannelResult.Ok)
        assertEquals(
            true,
            EnrollmentLink.parse(Samples.link(Samples.clientPayload, isPadded = true)) is ChannelResult.Ok,
        )
    }

    @Test
    fun nothingPastedIsLinkMissing() {
        assertEquals("link_missing", refusalOf("   "))
    }

    @Test
    fun somethingElseIsLinkUnreadable() {
        assertEquals("link_unreadable", refusalOf("https://example.com"))
        assertEquals("link_unreadable", refusalOf("neutrino://enroll/!!!"))
    }

    @Test
    fun aPayloadThatDoesNotInflateOrParseIsLinkUnreadable() {
        val encoder = Base64.getUrlEncoder().withoutPadding()
        val plain = encoder.encodeToString(Samples.clientPayload.toString().toByteArray())
        val garbled = encoder.encodeToString(Samples.deflate("{not json".toByteArray()))
        val cut = Samples.link(Samples.clientPayload).dropLast(8)
        assertEquals("link_unreadable", refusalOf("neutrino://enroll/$plain"))
        assertEquals("link_unreadable", refusalOf("neutrino://enroll/$garbled"))
        assertEquals("link_unreadable", refusalOf(cut))
    }

    @Test
    fun theOldShortFormIsLinkUnreadable() {
        assertEquals("link_unreadable", refusalOf("neutrino://enroll/t@192.168.100.1:8443/${Samples.FINGERPRINT}"))
    }

    @Test
    fun aLinkWithoutAddressTicketOrFingerprintIsIncomplete() {
        for (missing in listOf("urls", "token", "fp")) {
            assertEquals("link_incomplete", refusalOf(Samples.link(JsonObject(Samples.clientPayload - missing))))
        }
    }

    @Test
    fun aDevicesLinkIsNotForAClient() {
        val payload = JsonObject(Samples.clientPayload + ("role" to JsonPrimitive("agent")))
        val refusal = EnrollmentLink.parse(Samples.link(payload)) as ChannelResult.Refused
        assertEquals("link_not_for_client", refusal.code)
        assertEquals(mapOf("role" to "agent"), refusal.wordParams)
    }

    @Test
    fun aLinkWithoutOverlaysHasNone() {
        val payload = buildJsonObject {
            put("urls", buildJsonArray { add(JsonPrimitive("https://h:8443")) })
            put("token", "t")
            put("fp", Samples.FINGERPRINT)
            put("role", "client")
        }
        assertEquals(
            emptyList<ChannelOverlay>(),
            (EnrollmentLink.parse(Samples.link(payload)) as ChannelResult.Ok).value.overlays,
        )
    }
}
