package io.github.iffix.neutrino.screen

import io.github.iffix.neutrino.binding.HubBinding
import io.github.iffix.neutrino.channel.ChannelApp
import io.github.iffix.neutrino.channel.ChannelServiceEntry
import io.github.iffix.neutrino.channel.HubConnection
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.channel.HubWaitReason
import io.github.iffix.neutrino.design.DotTone
import io.github.iffix.neutrino.forward.PortForwardRow
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class AppsScreenTest {
    private val app = ChannelApp("gitea_d1", "Gitea", "module", "d1", "lab", "gitea.lab.localhost")
    private val web = entry("gitea_d1_web", "web", "url" to "https://10.0.0.5:3000/user/login?next=%2F", port = 27311)
    private val ssh = entry("gitea_d1_ssh", "port", "port" to "22", port = 30418)
    private val udp = entry("gitea_d1_7777_udp", "port", "protocol" to "udp", port = 25001)
    private val key = entry("ssh_server_d1_iffi", "ssh", "port" to "2201", port = 24555)
    private val hub = HubView(
        binding = HubBinding(id = "b1", gatewayUrl = "tcp://192.168.100.1:8443", token = "t"),
        connection = HubConnection.CONNECTED,
        services = listOf(web, ssh, key),
        apps = listOf(app),
    )

    private fun entry(id: String, type: String, field: Pair<String, String>, port: Int) = ChannelServiceEntry(
        id,
        type,
        "Gitea",
        JsonObject(mapOf(field.first to JsonPrimitive(field.second))),
        appId = "gitea_d1",
        localPort = port,
    )

    @Test
    fun anAppShowsItsWebAndPortEntriesAndLeavesItsSshOnesOut() {
        assertEquals(listOf(web, ssh), entriesOf(hub, app))
    }

    @Test
    fun eachEntryShowsItsFixedLocalAddress() {
        assertEquals("https://gitea.lab.localhost:27311/user/login?next=%2F", localAddressOf(app, web, 27311))
        assertEquals("gitea.lab.localhost:30418", localAddressOf(app, ssh, 30418))
        assertEquals("gitea.lab.localhost:25001/udp", localAddressOf(app, udp, 25001))
        assertEquals("127.0.0.1:30418", localAddressOf(app, ssh, 30418, host = "127.0.0.1"))
    }

    @Test
    fun theReasonLineSaysWhyUseOrConfigureIsDisabled() {
        assertNull(appReasonKey(hub, listOf(web), PortForwardRow()))
        assertEquals("ui.reason.disconnect_first", appReasonKey(hub, listOf(web), PortForwardRow(isInUse = true)))
        assertEquals("ui.reason.unhealthy", appReasonKey(hub, listOf(web.copy(isHealthy = false)), PortForwardRow()))
        val disabled = hub.copy(waitReason = HubWaitReason.DISABLED)
        assertEquals("ui.reason.disabled", appReasonKey(disabled, listOf(web), PortForwardRow()))
    }

    @Test
    fun theDotIsGreenWhileAnEntryAnswersAndAmberWhenNoneDoes() {
        assertEquals(DotTone.OK, appTone(hub, listOf(web, ssh.copy(isHealthy = false)), isBusy = false))
        assertEquals(DotTone.WAIT, appTone(hub, listOf(web.copy(isHealthy = false)), isBusy = false))
        assertEquals(DotTone.PULSE, appTone(hub, listOf(web), isBusy = true))
        assertEquals(DotTone.OK, appTone(hub, listOf(web.copy(isHealthy = null)), isBusy = false))
    }
}
