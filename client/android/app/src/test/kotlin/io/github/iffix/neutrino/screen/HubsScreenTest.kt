package io.github.iffix.neutrino.screen

import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.HubConnection
import io.github.iffix.neutrino.channel.HubJobs
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.channel.Samples
import io.github.iffix.neutrino.design.DotTone
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
                "ui.through.relay" to "Relay",
            ),
        )
        val before = HubView(Samples.binding, HubConnection.CONNECTED)
        assertEquals("Connected", hubStateWord(before, words))
        assertEquals("Connected · Relay", hubStateWord(before.copy(reachedThrough = "relay"), words))
        assertEquals("ui.state.down", hubStateKey(before.copy(connection = HubConnection.DOWN, reachedThrough = "lan")))
    }

    @Test
    fun aPanelJobIsAJobOnTheRow() {
        val row = HubView(Samples.binding, HubConnection.CONNECTED, jobs = HubJobs(isOpeningPanel = true))
        assertEquals(DotTone.PULSE, hubTone(row))
    }
}
