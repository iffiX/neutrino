package io.github.iffix.neutrino.screen

import io.github.iffix.neutrino.RepositoryFiles
import io.github.iffix.neutrino.channel.ChannelOverlay
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.HubConnection
import io.github.iffix.neutrino.channel.HubJobs
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.channel.Samples
import io.github.iffix.neutrino.design.DotTone
import io.github.iffix.neutrino.overlay.OverlayJob
import io.github.iffix.neutrino.overlay.OverlayLine
import io.github.iffix.neutrino.overlay.OverlayStage
import io.github.iffix.neutrino.overlay.OverlayState
import io.github.iffix.neutrino.words.WordCatalog
import org.junit.Assert.assertEquals
import org.junit.Test

class HubsScreenTest {
    private val pending = Samples.binding.copy(token = "", ticket = "ticket-1")

    @Test
    fun aPendingRowSaysPendingWithAGreyDot() {
        val row = HubView(pending, HubConnection.PENDING)
        assertEquals("ui.state.pending", hubStateKey(row))
        assertEquals(DotTone.OFF, hubTone(row))
        assertEquals(false, row.isJoinRefused)
    }

    @Test
    fun aRefusedTicketIsARedDownRow() {
        val row = HubView(pending, HubConnection.DOWN, lastError = ChannelResult.refused("ticket_spent"))
        assertEquals("ui.state.down", hubStateKey(row))
        assertEquals(DotTone.BAD, hubTone(row))
        assertEquals(true, row.isJoinRefused)
    }

    @Test
    fun anOrdinaryDownRowIsNoJoinRefusal() {
        assertEquals(false, HubView(Samples.binding, HubConnection.DOWN).isJoinRefused)
    }

    @Test
    fun aConnectedRowNamesTheWayInOnceTheStateNamesIt() {
        val words = WordCatalog(
            mapOf(
                "ui.state.connected" to "Connected",
                "ui.state.connected_through" to "Connected · {way}",
                "ui.through.relay" to "SSH Relay",
            ),
        )
        val before = HubView(Samples.binding, HubConnection.CONNECTED)
        assertEquals("Connected", hubStateWord(before, words))
        assertEquals("Connected · SSH Relay", hubStateWord(before.copy(reachedThrough = "relay"), words))
        assertEquals("ui.state.down", hubStateKey(before.copy(connection = HubConnection.DOWN, reachedThrough = "lan")))
    }

    @Test
    fun aConnectedRowCarriesTheWayInAndTheRoundTripAsTwoTags() {
        val words = WordCatalog(
            mapOf(
                "ui.state.connected_through" to "Connected · {way}",
                "ui.through.lan" to "LAN",
                "ui.state.rtt" to "{ms} ms",
            ),
        )
        val row = HubView(Samples.binding, HubConnection.CONNECTED, reachedThrough = "lan")
        assertEquals(listOf("Connected · LAN"), hubTags(row, words))
        assertEquals(listOf("Connected · LAN", "12 ms"), hubTags(row.copy(rttMs = 12), words))
        assertEquals(listOf("Connected · LAN", "7 ms"), hubTags(row.copy(rttMs = 7), words))
        assertEquals(emptyList<String>(), hubTags(row.copy(connection = HubConnection.CONNECTING, rttMs = 7), words))
        assertEquals(emptyList<String>(), hubTags(row.copy(jobs = HubJobs(isRefreshing = true), rttMs = 7), words))
    }

    @Test
    fun theVirtualNetworkLineReadsOnlyTheEngineNeverTheHub() {
        val words = WordCatalog(emptyMap())
        val lines = listOf(
            OverlayLine(),
            OverlayLine(network = "easytier", job = OverlayJob.CONNECTING, stage = OverlayStage.LOGIN),
            OverlayLine(state = OverlayState.ON, network = "easytier", address = "10.126.126.7"),
            OverlayLine(state = OverlayState.ON, network = "easytier", job = OverlayJob.DISCONNECTING),
        )
        assertEquals(
            listOf("ui.overlay.off", "ui.job.connecting", "ui.overlay.on", "ui.overlay.on"),
            lines.map { overlayStateWord(it, words) },
        )
        assertEquals(listOf("OFF", "ON"), OverlayState.entries.map { it.name })
        assertEquals(listOf("", "login"), OverlayStage.entries.map { it.wireName })
        val screen = RepositoryFiles.text(
            "client/android/app/src/main/kotlin/io/github/iffix/neutrino/screen/HubsScreen.kt",
        )
        for (key in listOf("ui.stage.hub", "ui.overlay.connecting")) assertEquals(false, key in screen)
    }

    @Test
    fun aDirectWayInIsNamedAndAnUnknownWayReadsAsConnected() {
        val words = WordCatalog(
            mapOf(
                "ui.state.connected" to "Connected",
                "ui.state.connected_through" to "Connected · {way}",
                "ui.through.direct" to "Direct",
            ),
        )
        val row = HubView(Samples.binding, HubConnection.CONNECTED)
        assertEquals("Connected · Direct", hubStateWord(row.copy(reachedThrough = "direct"), words))
        assertEquals("Connected", hubStateWord(row.copy(reachedThrough = "pigeon"), words))
    }

    @Test
    fun aHubThatPublishesNoNetworkHasNoNetworkLine() {
        val bare = HubView(Samples.binding.copy(overlays = emptyList()), HubConnection.CONNECTED)
        assertEquals(false, hasNetworkLine(bare))
        assertEquals(false, hasNetworkLine(bare.copy(connection = HubConnection.DISABLED)))
        val published = bare.copy(binding = bare.binding.copy(overlays = listOf(ChannelOverlay("easytier"))))
        assertEquals(true, hasNetworkLine(published))
        val stillOn = bare.copy(overlay = OverlayLine(state = OverlayState.ON, network = "easytier"))
        assertEquals(true, hasNetworkLine(stillOn))
        val screen = RepositoryFiles.text(
            "client/android/app/src/main/kotlin/io/github/iffix/neutrino/screen/HubsScreen.kt",
        )
        assertEquals(false, screen.contains("ui.reason.no_network"))
    }

    @Test
    fun aPanelJobIsAJobOnTheRow() {
        val row = HubView(Samples.binding, HubConnection.CONNECTED, jobs = HubJobs(isOpeningPanel = true))
        assertEquals(DotTone.PULSE, hubTone(row))
    }
}
