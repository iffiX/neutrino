package io.github.iffix.neutrino.remotedesktop

import io.github.iffix.neutrino.channel.ChannelResult
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class RemoteDesktopTargetTest {
    private fun material(vararg values: Pair<String, Any>) = ChannelResult.Ok(
        JsonObject(
            values.associate { (name, value) ->
                name to if (value is Int) JsonPrimitive(value) else JsonPrimitive(value.toString())
            },
        ),
    )

    @Test
    fun theHubsMaterialIsTheTarget() {
        val answer = RemoteDesktopTarget.of(
            "home:Argon",
            material("host" to "100.72.4.21", "port" to 21118, "password" to "seat"),
        )
        assertEquals(ChannelResult.Ok(RemoteDesktopTarget("home:Argon", "100.72.4.21", 21118, "seat")), answer)
    }

    @Test
    fun theHubsRefusalIsKept() {
        val refusal = ChannelResult.refused("rdp_not_shared", "service_id" to "rdp_s1")
        assertEquals(refusal, RemoteDesktopTarget.of("home:Argon", refusal))
    }

    @Test
    fun materialWithoutAnAddressIsRefused() {
        assertEquals(ChannelResult.refused("rdp_no_address"), RemoteDesktopTarget.of("a", material("port" to 21118)))
        assertEquals(ChannelResult.refused("rdp_no_address"), RemoteDesktopTarget.of("a", material("host" to "h")))
    }

    @Test
    fun theSeatPasswordStaysOutOfItsText() {
        assertFalse(RemoteDesktopTarget("a", "h", 1, "seat-secret").toString().contains("seat-secret"))
    }
}
