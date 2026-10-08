package io.github.iffix.neutrino.screen

import io.github.iffix.neutrino.RepositoryFiles
import io.github.iffix.neutrino.channel.ChannelOverlay
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.HubConnection
import io.github.iffix.neutrino.channel.HubJobs
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.channel.HubWaitReason
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

    private fun catalog(language: String) = WordCatalog(
        WordCatalog.flatten(RepositoryFiles.text("client/desktop/frontend/locales/$language.json")) +
            WordCatalog.flatten(RepositoryFiles.text("client/android/app/src/main/assets/locales/app/$language.json")),
    )

    private fun waiting(reason: HubWaitReason, nextRoundAtMillis: Long = 0, refusal: ChannelResult.Refused? = null) =
        HubView(
            Samples.binding,
            HubConnection.WAITING,
            waitReason = reason,
            waitRefusal = refusal,
            nextRoundAtMillis = nextRoundAtMillis,
            hasConnected = true,
        )

    @Test
    fun aJustJoinedRowReadsConnectingWithAPulsingDot() {
        val row = HubView(pending)
        assertEquals("ui.state.connecting", hubStateKey(row, 0))
        assertEquals("Connecting…", hubStateLine(row, catalog("en"), 0))
        assertEquals(DotTone.PULSE, hubTone(row))
        assertEquals(false, row.isLeaveOnly)
    }

    @Test
    fun eachWaitingReasonReadsItsStateLine() {
        val en = catalog("en")
        val ticketSpent = en.refusal("ticket_spent")
        val lines = listOf(
            waiting(HubWaitReason.HUB_SILENT, 5_000) to "The hub did not answer · retrying in 5 s",
            waiting(HubWaitReason.HUB_OFF_OVERLAY, 5_000) to "The hub is not on the virtual network · retrying in 5 s",
            waiting(HubWaitReason.NO_NETWORK) to "No network",
            waiting(HubWaitReason.UNTRUSTED, 60_000) to "Certificate mismatch · retrying in 60 s",
            waiting(HubWaitReason.ADMISSION_PAUSED, 42_000) to "The hub pauses new devices · retrying in 42 s",
            waiting(HubWaitReason.UNKNOWN_DEVICE) to "The hub does not know this device",
            waiting(HubWaitReason.TOO_OLD) to "Version too old",
            waiting(HubWaitReason.JOIN_REFUSED, refusal = ChannelResult.refused("ticket_spent")) to
                "Join refused · $ticketSpent",
            waiting(HubWaitReason.REPLACED) to "Replaced by another client · Reconnect",
            waiting(HubWaitReason.DISABLED) to "Disabled by the hub",
        )
        assertEquals(HubWaitReason.entries.toList(), lines.map { it.first.waitReason })
        for ((row, line) in lines) assertEquals(line, hubStateLine(row, en, 0))
        val zh = catalog("zh-CN")
        assertEquals("中枢未响应 · 5 秒后重试", hubStateLine(waiting(HubWaitReason.HUB_SILENT, 5_000), zh, 0))
        assertEquals("已被替换 · 重新连接", hubStateLine(waiting(HubWaitReason.REPLACED), zh, 0))
        assertEquals("已停用", hubStateLine(waiting(HubWaitReason.DISABLED), zh, 0))
    }

    @Test
    fun theCountdownCountsTheSecondsLeftAndReadsConnectingAtZero() {
        val en = catalog("en")
        val row = waiting(HubWaitReason.HUB_SILENT, 10_000)
        assertEquals(
            listOf(10L, 10L, 9L, 1L, 0L, 0L),
            listOf(0L, 1L, 1_000L, 9_001L, 10_000L, 12_000L).map {
                secondsToNextRound(row, it)
            },
        )
        assertEquals("The hub did not answer · retrying in 9 s", hubStateLine(row, en, 1_000))
        assertEquals("Connecting…", hubStateLine(row, en, 10_000))
        assertEquals(null, secondsToNextRound(waiting(HubWaitReason.NO_NETWORK), 0))
        assertEquals(null, secondsToNextRound(HubView(Samples.binding, nextRoundAtMillis = 10_000), 0))
    }

    @Test
    fun theDotIsRedForAReasonAPersonActsOnAndAmberOtherwise() {
        val red = setOf(
            HubWaitReason.UNTRUSTED,
            HubWaitReason.UNKNOWN_DEVICE,
            HubWaitReason.TOO_OLD,
            HubWaitReason.JOIN_REFUSED,
        )
        for (reason in HubWaitReason.entries) {
            assertEquals(reason.name, if (reason in red) DotTone.BAD else DotTone.WAIT, hubTone(waiting(reason)))
        }
        val neverReached = waiting(HubWaitReason.HUB_SILENT, 5_000).copy(hasConnected = false)
        assertEquals(DotTone.OFF, hubTone(neverReached))
        assertEquals(DotTone.BAD, hubTone(waiting(HubWaitReason.JOIN_REFUSED).copy(hasConnected = false)))
    }

    @Test
    fun aRefusedTicketOrAnUnknownDeviceLeavesLeaveAsTheOneAction() {
        assertEquals(true, waiting(HubWaitReason.JOIN_REFUSED).isLeaveOnly)
        assertEquals(true, waiting(HubWaitReason.UNKNOWN_DEVICE).isLeaveOnly)
        assertEquals(false, waiting(HubWaitReason.HUB_SILENT).isLeaveOnly)
        assertEquals(false, waiting(HubWaitReason.REPLACED).isLeaveOnly)
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
        assertEquals("Connected", hubStateWord(before, words, 0))
        assertEquals("Connected · SSH Relay", hubStateWord(before.copy(reachedThrough = "relay"), words, 0))
        val down = before.copy(connection = HubConnection.WAITING, waitReason = HubWaitReason.HUB_SILENT)
        assertEquals("ui.state.hub_silent", hubStateKey(down.copy(reachedThrough = "lan"), 0))
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
        assertEquals("Connected · Direct", hubStateWord(row.copy(reachedThrough = "direct"), words, 0))
        assertEquals("Connected", hubStateWord(row.copy(reachedThrough = "pigeon"), words, 0))
    }

    @Test
    fun aHubThatPublishesNoNetworkHasNoNetworkLine() {
        val bare = HubView(Samples.binding.copy(overlays = emptyList()), HubConnection.CONNECTED)
        assertEquals(false, hasNetworkLine(bare))
        val disabled = bare.copy(connection = HubConnection.WAITING, waitReason = HubWaitReason.DISABLED)
        assertEquals(false, hasNetworkLine(disabled))
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
