package io.github.iffix.neutrino.screen

import io.github.iffix.neutrino.binding.HubBinding
import io.github.iffix.neutrino.channel.ChannelApp
import io.github.iffix.neutrino.channel.ChannelServiceEntry
import io.github.iffix.neutrino.channel.HubConnection
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.channel.HubWaitReason
import io.github.iffix.neutrino.design.DotTone
import io.github.iffix.neutrino.forward.PortForwardRow
import io.github.iffix.neutrino.words.WordCatalog
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
        binding = HubBinding(id = "b1", hubName = "Home", gatewayUrl = "tcp://192.168.100.1:8443", token = "t"),
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

    private val words = WordCatalog(
        mapOf(
            "ui.unhealthy" to "Not reachable now",
            "ui.app_source.module" to "module",
            "ui.app_provided_by" to "from {hub}:{machine} · {source}",
        ),
    )

    @Test
    fun anUnhealthyEntrySaysSoAfterItsAddress() {
        assertEquals(
            "https://gitea.lab.localhost:27311/user/login?next=%2F · Not reachable now",
            entryLineOf(app, web.copy(isHealthy = false), 27311, words),
        )
    }

    @Test
    fun theProviderLineNamesTheEntrysHostWhenTheHubNamesNoMachine() {
        assertEquals("from Home:lab · module", appProviderLine(hub, app, listOf(web), words))
        val manual = app.copy(deviceName = "", source = "other")
        val v6 = entry("v6", "web", "url" to "http://[fd00::5]:3000/", port = 1)
        assertEquals("from Home:fd00::5 · ", appProviderLine(hub, manual, listOf(v6), words))
        val port = entry("p", "port", "host" to "10.0.0.9", port = 1)
        assertEquals("from Home:10.0.0.9 · ", appProviderLine(hub, manual, listOf(port), words))
    }

    @Test
    fun theReasonLineSaysWhyUseOrConfigureIsDisabled() {
        assertNull(appReasonKey(hub, listOf(web), PortForwardRow(), hasPage = false))
        assertEquals("ui.reason.use_first", appReasonKey(hub, listOf(web), PortForwardRow(), hasPage = true))
        assertEquals(
            "ui.reason.disconnect_first",
            appReasonKey(hub, listOf(web), PortForwardRow(isInUse = true), hasPage = true),
        )
        val down = listOf(web.copy(isHealthy = false))
        assertEquals("ui.reason.unhealthy", appReasonKey(hub, down, PortForwardRow(), hasPage = true))
        assertEquals("ui.reason.disconnect_first", appReasonKey(hub, down, PortForwardRow(isInUse = true), true))
        val disabled = hub.copy(waitReason = HubWaitReason.DISABLED)
        assertEquals("ui.reason.disabled", appReasonKey(disabled, listOf(web), PortForwardRow(), hasPage = false))
    }

    @Test
    fun theDotIsGreenWhileAnEntryAnswersAndAmberWhenNoneDoes() {
        assertEquals(DotTone.OK, appTone(hub, listOf(web, ssh.copy(isHealthy = false)), isBusy = false))
        assertEquals(DotTone.WAIT, appTone(hub, listOf(web.copy(isHealthy = false)), isBusy = false))
        assertEquals(DotTone.PULSE, appTone(hub, listOf(web), isBusy = true))
        assertEquals(DotTone.OK, appTone(hub, listOf(web.copy(isHealthy = null)), isBusy = false))
    }
}
