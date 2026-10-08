package io.github.iffix.neutrino

import io.github.iffix.neutrino.channel.HubConnection
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.channel.HubWaitReason
import io.github.iffix.neutrino.channel.Samples
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Test

class ClientCoreHoldTest {
    private val first = Samples.binding
    private val second = Samples.binding.copy(id = "b2")

    @Test
    fun theServiceRunsFromTheFirstBindingToTheLastLeave() = runTest {
        val bindings = flowOf(emptyList(), listOf(first), listOf(first, second), listOf(second), emptyList())
        assertEquals(listOf(false, true, false), ClientCoreHold.changes(bindings).toList())
    }

    @Test
    fun anAppStartWithABindingRunsTheService() = runTest {
        assertEquals(listOf(true), ClientCoreHold.changes(flowOf(listOf(first))).toList())
    }

    @Test
    fun theNotificationCountsTheHubsWithAnOpenChannel() {
        val hubs = listOf(
            HubView(first, connection = HubConnection.CONNECTED),
            HubView(second, connection = HubConnection.WAITING, waitReason = HubWaitReason.DISABLED),
            HubView(first.copy(id = "b3"), connection = HubConnection.CONNECTING),
            HubView(first.copy(id = "b4"), connection = HubConnection.WAITING),
        )
        assertEquals(2, ClientCoreHold.connectedCount(hubs))
    }
}
