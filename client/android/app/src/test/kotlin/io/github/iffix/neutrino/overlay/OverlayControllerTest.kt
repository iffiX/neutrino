package io.github.iffix.neutrino.overlay

import io.github.iffix.neutrino.binding.BindingStore
import io.github.iffix.neutrino.binding.FakeSecretSealer
import io.github.iffix.neutrino.channel.ChannelOverlay
import io.github.iffix.neutrino.channel.ChannelOverlayRoute
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.Samples
import java.net.InetAddress
import kotlinx.coroutines.ExperimentalCoroutinesApi
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

    private val netbird =
        ChannelOverlay(provider = "netbird", setupKey = "k", fqdn = "hub.netbird.cloud", hubAddress = "100.88.0.1")
    private val easytier = ChannelOverlay(
        provider = "easytier",
        networkName = "n",
        networkSecret = "s",
        peer = "tcp://p:1",
        hubAddress = "10.126.126.1",
    )
    private val overUrl = "https://100.88.0.1:8443"
    private val started = mutableListOf<Pair<String, String>>()
    private var stops = 0
    private val routes = mutableListOf<Pair<String, ChannelOverlayRoute?>>()
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
        return OverlayController(store, launcher, backgroundScope) { id, route -> routes += id to route }
    }

    private fun OverlayController.line(id: String = "b1") = lines.value[id] ?: OverlayLine()

    private fun OverlayController.engineSays(phase: OverlayPhase, address: String = "", code: String? = null) =
        report(OverlayStatus("b1", "netbird", phase, address, code?.let { ChannelResult.refused(it) }))

    @Test
    fun connectIsTheConnectingJobInItsLoginStageWhileTheLineStaysOff() = runTest {
        val controller = controller()
        controller.connect("b1")
        assertEquals(listOf("b1" to "netbird"), started)
        assertEquals(OverlayState.OFF, controller.line().state)
        assertEquals(OverlayJob.CONNECTING, controller.line().job)
        assertEquals(OverlayStage.LOGIN, controller.line().stage)
    }

    @Test
    fun anAddressIsOnAtOnceAndHandsTheHubsAddressOnTheNetworkToTheChannel() = runTest {
        val controller = controller()
        controller.connect("b1")
        controller.engineSays(OverlayPhase.ON, "100.72.4.9/16")
        assertEquals(OverlayState.ON, controller.line().state)
        assertEquals(OverlayJob.NONE, controller.line().job)
        assertEquals(OverlayStage.NONE, controller.line().stage)
        assertEquals("100.72.4.9", controller.line().address)
        assertTrue(store.get("b1")?.isOverlayOn == true)
        val (id, route) = routes.single()
        assertEquals("b1", id)
        assertEquals(overUrl, route?.url)
        assertEquals("netbird", route?.provider)
        assertEquals(InetAddress.getByName("100.72.4.9"), route?.network?.address)
        assertEquals(16, route?.network?.prefix)
    }

    @Test
    fun theOnLineWaitsForNothingFromTheHub() = runTest {
        val controller = controller()
        controller.connect("b1")
        controller.engineSays(OverlayPhase.ON, "100.72.4.9")
        advanceTimeBy(600_000)
        assertEquals(OverlayState.ON, controller.line().state)
        assertNull(controller.line().error)
        assertEquals(0, stops)
    }

    @Test
    fun aConsoleThatHasThePhoneRegisteredHoldsTheConnectWithNoDeadlineUntilCancel() = runTest {
        val controller = controller()
        controller.connect("b1")
        controller.engineSays(OverlayPhase.WAITING)
        assertTrue(controller.line().isWaiting)
        advanceTimeBy(600_000)
        assertEquals(OverlayJob.CONNECTING, controller.line().job)
        assertEquals(0, stops)
        controller.cancel("b1")
        assertEquals(OverlayState.OFF, controller.line().state)
        assertEquals(OverlayJob.NONE, controller.line().job)
        assertNull(controller.line().error)
        assertFalse(controller.line().isWaiting)
        assertEquals(1, stops)
    }

    @Test
    fun aNetworkTheConsoleAssignsIsOn() = runTest {
        val controller = controller()
        controller.connect("b1")
        controller.engineSays(OverlayPhase.WAITING)
        advanceTimeBy(300_000)
        controller.engineSays(OverlayPhase.ON, "10.144.0.7/24")
        assertFalse(controller.line().isWaiting)
        assertEquals(OverlayState.ON, controller.line().state)
    }

    @Test
    fun noAddressWithinNinetySecondsIsOffWithTheCode() = runTest {
        val controller = controller()
        controller.connect("b1")
        advanceTimeBy(89_999)
        assertEquals(OverlayJob.CONNECTING, controller.line().job)
        advanceTimeBy(2)
        assertEquals(OverlayState.OFF, controller.line().state)
        assertEquals(OverlayJob.NONE, controller.line().job)
        assertEquals("overlay_no_address", controller.line().error?.code)
        assertEquals(1, stops)
        assertEquals(listOf("b1" to "netbird"), started)
    }

    @Test
    fun anAddressAfterALongLoginEndsTheLoginLimit() = runTest {
        val controller = controller()
        controller.connect("b1")
        advanceTimeBy(85_000)
        controller.engineSays(OverlayPhase.ON, "100.72.4.9/16")
        advanceTimeBy(10_000)
        assertEquals(OverlayState.ON, controller.line().state)
        assertNull(controller.line().error)
    }

    @Test
    fun cancelStopsTheEngineAndIsOffWithNoError() = runTest {
        val controller = controller()
        controller.connect("b1")
        advanceTimeBy(30_000)
        controller.cancel("b1")
        assertEquals(OverlayState.OFF, controller.line().state)
        assertEquals(OverlayStage.NONE, controller.line().stage)
        assertNull(controller.line().error)
        assertEquals(1, stops)
        advanceTimeBy(61_000)
        assertNull(controller.line().error)
    }

    @Test
    fun theEngineFailingIsOffWithItsCodeAndNothingRetries() = runTest {
        val controller = controller()
        controller.connect("b1")
        controller.engineSays(OverlayPhase.FAILED, code = "overlay_join_failed")
        assertEquals(OverlayState.OFF, controller.line().state)
        assertEquals("overlay_join_failed", controller.line().error?.code)
        advanceTimeBy(120_000)
        controller.follow(store.bindings.value)
        assertEquals(1, started.size)
    }

    @Test
    fun aWithdrawnNetworkIsOffAndLeavesTheChannel() = runTest {
        val controller = controller()
        controller.connect("b1")
        controller.engineSays(OverlayPhase.ON, "100.72.4.9")
        store.update("b1") { it.copy(overlays = listOf(easytier)) }
        controller.follow(store.bindings.value)
        assertEquals(OverlayState.OFF, controller.line().state)
        assertEquals("overlay_withdrawn", controller.line().error?.code)
        assertEquals(listOf("b1" to "netbird"), started)
        assertFalse(store.get("b1")?.isOverlayOn == true)
        assertEquals("b1" to null, routes.last())
    }

    @Test
    fun disconnectWaitsForTheEngineToStop() = runTest {
        val controller = controller()
        controller.connect("b1")
        controller.engineSays(OverlayPhase.ON, "100.72.4.9")
        controller.disconnect("b1")
        assertEquals(OverlayJob.DISCONNECTING, controller.line().job)
        assertEquals(OverlayState.ON, controller.line().state)
        controller.engineSays(OverlayPhase.OFF)
        assertEquals(OverlayState.OFF, controller.line().state)
        assertNull(controller.line().error)
        assertEquals(1, stops)
        assertEquals("b1" to null, routes.last())
    }

    @Test
    fun theEngineStoppingByItselfWhileOnIsOffWithACode() = runTest {
        val controller = controller()
        controller.connect("b1")
        controller.engineSays(OverlayPhase.ON, "100.72.4.9")
        controller.engineSays(OverlayPhase.OFF)
        assertEquals(OverlayState.OFF, controller.line().state)
        assertEquals("overlay_engine_stopped", controller.line().error?.code)
    }

    @Test
    fun aSecondNetworkIsNotStartedWhileOneRuns() = runTest {
        val controller = controller()
        controller.connect("b1")
        controller.connect("b2")
        controller.connect("b1")
        assertEquals(listOf("b1" to "netbird"), started)
        assertEquals(OverlayJob.NONE, controller.line("b2").job)
    }

    @Test
    fun thePickChangesOnlyWhileOffAndIdle() = runTest {
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
        controller.start()
        runCurrent()
        assertEquals(listOf("b2" to "netbird"), started)
        advanceTimeBy(90_001)
        assertEquals(OverlayState.OFF, controller.line("b2").state)
        assertFalse(store.get("b2")?.isOverlayOn == true)
        assertEquals(1, started.size)
    }

    @Test
    fun theHubsAddressOnTheNetworkComesFromTheMaterialFirst() = runTest {
        val controller = controller()
        controller.pick("b1", "easytier")
        controller.connect("b1")
        controller.report(OverlayStatus("b1", "easytier", OverlayPhase.ON, "10.126.126.7/24"))
        assertEquals("https://10.126.126.1:8443", routes.single().second?.url)
        assertEquals("easytier", routes.single().second?.provider)
    }

    @Test
    fun aRefreshDropsTheErrorAndKeepsTheState() = runTest {
        val controller = controller()
        controller.connect("b1")
        controller.engineSays(OverlayPhase.FAILED, code = "overlay_join_failed")
        controller.clearErrors()
        assertNull(controller.line().error)
        assertEquals(OverlayState.OFF, controller.line().state)
    }

    @Test
    fun aRevokedVpnIsOffWithACode() = runTest {
        val controller = controller()
        controller.connect("b1")
        controller.revoked()
        assertEquals("overlay_not_authorized", controller.line().error?.code)
    }

    @Test
    fun aReportFromAnEngineThatDoesNotRunIsDropped() = runTest {
        val controller = controller()
        controller.connect("b1")
        controller.report(OverlayStatus("b1", "easytier", OverlayPhase.FAILED))
        assertEquals(OverlayJob.CONNECTING, controller.line().job)
    }
}
