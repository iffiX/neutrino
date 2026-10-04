package io.github.iffix.neutrino.remotedesktop

import io.github.iffix.neutrino.channel.ChannelResult
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class RemoteDesktopTargetTest {
    @Test
    fun theViewerDialsTheForwardWithTheHubsSeatPassword() {
        val answer = RemoteDesktopTarget.of(
            "home:Argon",
            ChannelResult.Ok(JsonObject(mapOf("password" to JsonPrimitive("seat")))),
            21118,
        )
        assertEquals(ChannelResult.Ok(RemoteDesktopTarget("home:Argon", "127.0.0.1", 21118, "seat")), answer)
    }

    @Test
    fun theHubsRefusalIsKept() {
        val refusal = ChannelResult.refused("rdp_not_shared", "service_id" to "rdp_s1")
        assertEquals(refusal, RemoteDesktopTarget.of("home:Argon", refusal, 21118))
    }

    @Test
    fun theSeatPasswordStaysOutOfItsText() {
        assertFalse(RemoteDesktopTarget("a", "h", 1, "seat-secret").toString().contains("seat-secret"))
    }
}
