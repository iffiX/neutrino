package io.github.iffix.neutrino.overlay

import io.github.iffix.neutrino.binding.BindingStore
import io.github.iffix.neutrino.binding.FakeSecretSealer
import io.github.iffix.neutrino.channel.ChannelOverlay
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.HubConnection
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.channel.Samples
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

@OptIn(ExperimentalCoroutinesApi::class)
class OverlayControllerTest {
    @get:Rule
    val folder = TemporaryFolder()

    private val netbird = ChannelOverlay(provider = "netbird", setupKey = "k", fqdn = "hub.netbird.cloud")
    private val easytier = ChannelOverlay(
        provider = "easytier",
        networkName = "n",
        networkSecret = "s",
        peer = "tcp://p:1",
        hubAddress = "10.126.126.1",
    )
    private val overUrl = "https://hub.netbird.cloud:8443"
    private val started = mutableListOf<Pair<String, String>>()
    private var stops = 0
    private val preferred = mutableListOf<Pair<String, String>>()
    private val launcher = object : OverlayLauncher {
        override fun start(bindingId: String, provider: String) {
            started += bindingId to provider
        }

        override fun stop() {
            stops += 1
        }
    }
    private lateinit var store: BindingStore

    private fun TestScope.controller(): OverlayController {
        store = BindingStore(folder.root.resolve("b.sealed"), FakeSecretSealer())
        store.put(Samples.binding.copy(overlays = listOf(netbird, easytier)))
        store.put(Samples.binding.copy(id = "b2", overlays = listOf(netbird)))
        return OverlayController(store, launcher, backgroundScope) { id, url -> preferred += id to url }
    }

    private fun views(address: String = "https://192.168.100.1:8443") = store.bindings.value.map {
        HubView(it, connection = HubConnection.CONNECTED, connectedAddress = address)
    }

    private fun OverlayController.state(id: String = "b1") = lines.value[id]?.state ?: OverlayState.OFF

    private fun OverlayController.engineSays(phase: OverlayPhase, address: String = "", code: String? = null) =
        report(OverlayStatus("b1", "netbird", phase, address, code?.let { ChannelResult.refused(it) }))

    @Test
    fun connectRunsThePickedNetworkAsOneAttempt() = runTest {
        val controller = controller()
        controller.connect("b1")
        assertEquals(listOf("b1" to "netbird"), started)
        assertEquals(OverlayState.CONNECTING, controller.state())
        assertEquals(OverlayJob.CONNECTING, controller.lines.value["b1"]?.job)
    }

    @Test
    fun anAddressThenTheChannelThroughTheNetworkIsOn() = runTest {
        val controller = controller()
        controller.connect("b1")
        controller.engineSays(OverlayPhase.ON, "100.72.4.9")
        assertEquals(listOf("b1" to overUrl), preferred)
        controller.follow(store.bindings.value, views())
        assertEquals(OverlayState.CONNECTING, controller.state())
        controller.follow(store.bindings.value, views(overUrl))
        assertEquals(OverlayState.ON, controller.state())
        assertEquals("100.72.4.9", controller.lines.value["b1"]?.address)
        assertEquals(OverlayJob.NONE, controller.lines.value["b1"]?.job)
        assertTrue(store.get("b1")?.isOverlayOn == true)
    }

    @Test
    fun noAddressWithinSixtySecondsIsOffWithTheCode() = runTest {
        val controller = controller()
        controller.connect("b1")
        advanceTimeBy(59_999)
        assertEquals(OverlayState.CONNECTING, controller.state())
        advanceTimeBy(2)
        assertEquals(OverlayState.OFF, controller.state())
        assertEquals("overlay_no_address", controller.lines.value["b1"]?.error?.code)
        assertEquals(1, stops)
        assertEquals(listOf("b1" to "netbird"), started)
    }

    @Test
    fun noChannelThroughTheNetworkWithinSixtySecondsIsOffWithTheCode() = runTest {
        val controller = controller()
        controller.connect("b1")
        controller.engineSays(OverlayPhase.ON, "100.72.4.9")
        advanceTimeBy(60_001)
        assertEquals(OverlayState.OFF, controller.state())
        assertEquals("overlay_hub_unreachable", controller.lines.value["b1"]?.error?.code)
        assertEquals(listOf("b1" to overUrl, "b1" to ""), preferred)
    }

    @Test
    fun cancelStopsTheEngineAndIsOffWithNoError() = runTest {
        val controller = controller()
        controller.connect("b1")
        controller.cancel("b1")
        assertEquals(OverlayState.OFF, controller.state())
        assertNull(controller.lines.value["b1"]?.error)
        assertEquals(1, stops)
        advanceTimeBy(61_000)
        assertNull(controller.lines.value["b1"]?.error)
    }

    @Test
    fun theEngineFailingIsOffWithItsCodeAndNothingRetries() = runTest {
        val controller = controller()
        controller.connect("b1")
        controller.engineSays(OverlayPhase.FAILED, code = "overlay_join_failed")
        assertEquals(OverlayState.OFF, controller.state())
        assertEquals("overlay_join_failed", controller.lines.value["b1"]?.error?.code)
        advanceTimeBy(120_000)
        controller.follow(store.bindings.value, views())
        assertEquals(1, started.size)
    }

    @Test
    fun aNetworkTheHubWithdrewIsOffWithOverlayWithdrawn() = runTest {
        val controller = controller()
        controller.connect("b1")
        controller.engineSays(OverlayPhase.ON, "100.72.4.9")
        controller.follow(store.bindings.value, views(overUrl))
        store.update("b1") { it.copy(overlays = listOf(easytier)) }
        controller.follow(store.bindings.value, views(overUrl))
        assertEquals(OverlayState.OFF, controller.state())
        assertEquals("overlay_withdrawn", controller.lines.value["b1"]?.error?.code)
        assertEquals(listOf("b1" to "netbird"), started)
        assertFalse(store.get("b1")?.isOverlayOn == true)
    }

    @Test
    fun disconnectWaitsForTheEngineToStop() = runTest {
        val controller = controller()
        controller.connect("b1")
        controller.engineSays(OverlayPhase.ON, "100.72.4.9")
        controller.follow(store.bindings.value, views(overUrl))
        controller.disconnect("b1")
        assertEquals(OverlayJob.DISCONNECTING, controller.lines.value["b1"]?.job)
        assertEquals(OverlayState.ON, controller.state())
        controller.engineSays(OverlayPhase.OFF)
        assertEquals(OverlayState.OFF, controller.state())
        assertNull(controller.lines.value["b1"]?.error)
        assertEquals(1, stops)
    }

    @Test
    fun theEngineStoppingByItselfWhileOnIsOffWithACode() = runTest {
        val controller = controller()
        controller.connect("b1")
        controller.engineSays(OverlayPhase.ON, "100.72.4.9")
        controller.follow(store.bindings.value, views(overUrl))
        controller.engineSays(OverlayPhase.OFF)
        assertEquals("overlay_engine_stopped", controller.lines.value["b1"]?.error?.code)
    }

    @Test
    fun aSecondNetworkIsNotStartedWhileOneRuns() = runTest {
        val controller = controller()
        controller.connect("b1")
        controller.connect("b2")
        controller.connect("b1")
        assertEquals(listOf("b1" to "netbird"), started)
        assertEquals(OverlayState.OFF, controller.state("b2"))
    }

    @Test
    fun thePickChangesOnlyWhileOff() = runTest {
        val controller = controller()
        controller.pick("b1", "easytier")
        assertEquals("easytier", store.get("b1")?.overlayChoice)
        controller.connect("b1")
        controller.pick("b1", "netbird")
        assertEquals("easytier", store.get("b1")?.overlayChoice)
        assertEquals(listOf("b1" to "easytier"), started)
    }

    @Test
    fun aBindingLastOnIsConnectedOnceAtStart() = runTest {
        val controller = controller()
        store.update("b2") { it.copy(isOverlayOn = true) }
        controller.start(MutableStateFlow(views()))
        runCurrent()
        assertEquals(listOf("b2" to "netbird"), started)
        advanceTimeBy(60_001)
        assertEquals(OverlayState.OFF, controller.state("b2"))
        assertFalse(store.get("b2")?.isOverlayOn == true)
        assertEquals(1, started.size)
    }

    @Test
    fun aRefreshDropsTheErrorAndKeepsTheState() = runTest {
        val controller = controller()
        controller.connect("b1")
        controller.engineSays(OverlayPhase.FAILED, code = "overlay_join_failed")
        controller.clearErrors()
        assertNull(controller.lines.value["b1"]?.error)
        assertEquals(OverlayState.OFF, controller.state())
    }

    @Test
    fun aRevokedVpnIsOffWithACode() = runTest {
        val controller = controller()
        controller.connect("b1")
        controller.revoked()
        assertEquals("overlay_not_authorized", controller.lines.value["b1"]?.error?.code)
    }

    @Test
    fun aReportFromAnEngineThatDoesNotRunIsDropped() = runTest {
        val controller = controller()
        controller.connect("b1")
        controller.report(OverlayStatus("b1", "easytier", OverlayPhase.FAILED))
        assertEquals(OverlayState.CONNECTING, controller.state())
    }
}
