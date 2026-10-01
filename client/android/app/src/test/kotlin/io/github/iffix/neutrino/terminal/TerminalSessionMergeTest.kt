package io.github.iffix.neutrino.terminal

import io.github.iffix.neutrino.channel.ChannelTerminal
import io.github.iffix.neutrino.channel.ChannelTerminalSession
import io.github.iffix.neutrino.channel.HubConnection
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.channel.Samples
import org.junit.Assert.assertEquals
import org.junit.Test

class TerminalSessionMergeTest {
    private val owned = ChannelTerminalSession(
        sessionId = "s1",
        owner = "client:b1",
        isOwned = true,
        isPersistent = true,
        attachedCount = 1,
        title = "zsh",
    )
    private val shared = ChannelTerminalSession(
        sessionId = "s2",
        owner = "hub",
        isOwned = false,
        isShared = true,
        attachedCount = 2,
    )

    private fun hub(id: String, connection: HubConnection, vararg sessions: ChannelTerminalSession) = HubView(
        Samples.binding.copy(id = id),
        connection = connection,
        terminals = listOf(ChannelTerminal("d-$id", "Argon", true, sessions.toList())),
    )

    private fun merge(tabs: List<TerminalTab>, vararg hubs: HubView, dismissed: Set<String> = emptySet()) =
        TerminalSessionMerge.listed(hubs.toList()).let { (listings, listedHubs) ->
            TerminalSessionMerge.merge(tabs, listings, listedHubs, dismissed)
        }

    @Test
    fun everyListedSessionGetsATabAtTheEndInTheListsOrder() {
        val local = TerminalTab("s0", "b1", "d-b1", "Argon", phase = TerminalPhase.OPEN)
        val tabs = merge(listOf(local), hub("b1", HubConnection.CONNECTED, owned, shared))
        assertEquals(listOf("s0", "s1", "s2"), tabs.map { it.sessionId })
        val second = tabs[1]
        assertEquals(TerminalPhase.DETACHED, second.phase)
        assertEquals("d-b1", second.deviceId)
        assertEquals(true, second.isListed)
        assertEquals(true, second.isPersistent)
        assertEquals(false, tabs[2].isOwned)
        assertEquals("hub", tabs[2].owner)
        assertEquals(2, tabs[2].attachedCount)
    }

    @Test
    fun aListedTabTakesTheListsValues() {
        val before = merge(emptyList(), hub("b1", HubConnection.CONNECTED, owned))
        val after = merge(before, hub("b1", HubConnection.CONNECTED, owned.copy(isShared = true, attachedCount = 3)))
        assertEquals(true, after.single().isShared)
        assertEquals(3, after.single().attachedCount)
    }

    @Test
    fun aTabWhoseSessionLeftTheListHasEndedAndStays() {
        val before = merge(emptyList(), hub("b1", HubConnection.CONNECTED, owned))
        val after = merge(before, hub("b1", HubConnection.CONNECTED))
        assertEquals(TerminalPhase.ENDED, after.single().phase)
        assertEquals(0, after.single().attachedCount)
    }

    @Test
    fun aTabNotYetListedIsLeftAsItIs() {
        val local = TerminalTab("s0", "b1", "d-b1", "Argon", phase = TerminalPhase.OPEN)
        assertEquals(listOf(local), merge(listOf(local), hub("b1", HubConnection.CONNECTED)))
    }

    @Test
    fun aHubThatIsNotConnectedLeavesItsTabsAndListsNothing() {
        val before = merge(emptyList(), hub("b1", HubConnection.CONNECTED, owned))
        val after = merge(before, hub("b1", HubConnection.DOWN), hub("b2", HubConnection.DOWN, shared))
        assertEquals(before, after)
    }

    @Test
    fun aDismissedSessionGetsNoTab() {
        assertEquals(
            emptyList<TerminalTab>(),
            merge(emptyList(), hub("b1", HubConnection.CONNECTED, owned), dismissed = setOf("s1")),
        )
    }
}
