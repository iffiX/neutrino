package io.github.iffix.neutrino.screen

import io.github.iffix.neutrino.channel.ChannelServiceEntry
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Test

class RemoteDesktopScreenTest {
    private fun desktop(payload: String) =
        ChannelServiceEntry("rdp_s1", "rdp", "workshop", Json.parseToJsonElement(payload).jsonObject)

    @Test
    fun aMacsDesktopCarriesTheHint() {
        assertEquals(true, hasMacHint(desktop("""{"host": "192.0.2.5", "platform_os": "darwin"}""")))
    }

    @Test
    fun anotherSystemsDesktopCarriesNone() {
        assertEquals(false, hasMacHint(desktop("""{"platform_os": "linux"}""")))
        assertEquals(false, hasMacHint(desktop("""{"platform_os": "windows"}""")))
    }

    @Test
    fun aDesktopFromAnOlderHubCarriesNone() {
        assertEquals(false, hasMacHint(desktop("""{"host": "192.0.2.5"}""")))
    }
}
