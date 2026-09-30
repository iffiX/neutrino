package io.github.iffix.neutrino.overlay

import io.github.iffix.neutrino.binding.BindingStore
import io.github.iffix.neutrino.binding.FakeSecretSealer
import io.github.iffix.neutrino.channel.ChannelOverlay
import io.github.iffix.neutrino.channel.HubConnection
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.channel.Samples
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class OverlayControllerTest {
    @get:Rule
    val folder = TemporaryFolder()

    private val netbird = ChannelOverlay(provider = "netbird", setupKey = "k")
    private val easytier =
        ChannelOverlay(provider = "easytier", networkName = "n", networkSecret = "s", peer = "tcp://p:1")
    private var now = 0L
    private val started = mutableListOf<Pair<String, String>>()
    private var stops = 0
    private val movedOver = mutableListOf<String>()
    private val launcher = object : OverlayLauncher {
        override fun start(bindingId: String, provider: String) {
            started += bindingId to provider
        }

        override fun stop() {
            stops += 1
        }
    }

    private fun setUp(): Pair<OverlayController, BindingStore> {
        val store = BindingStore(folder.root.resolve("b.sealed"), FakeSecretSealer())
        store.put(Samples.binding.copy(overlays = listOf(netbird, easytier)))
        store.put(Samples.binding.copy(id = "b2", overlays = listOf(netbird)))
        return OverlayController(store, launcher, { now }) { movedOver += it } to store
    }

    private fun views(store: BindingStore, isConnected: Boolean) = store.bindings.value.map {
        HubView(it, connection = if (isConnected) HubConnection.CONNECTED else HubConnection.RECONNECTING)
    }

    @Test
    fun wantingAHubRunsItsFirstNetwork() {
        val (controller, store) = setUp()
        controller.setWanted("b1", true)
        controller.reconcile(store.bindings.value, views(store, true))
        assertEquals(listOf("b1" to "netbird"), started)
        assertEquals(OverlayPhase.JOINING, controller.status.value?.phase)
    }

    @Test
    fun wantingOneHubClearsTheOthersWish() {
        val (controller, store) = setUp()
        controller.setWanted("b2", true)
        controller.setWanted("b1", true)
        assertEquals(listOf(true, false), store.bindings.value.map { it.isOverlayWanted })
    }

    @Test
    fun aChannelLostPastThirtySecondsMovesOverAndReconnects() {
        val (controller, store) = setUp()
        controller.setWanted("b1", true)
        controller.reconcile(store.bindings.value, views(store, true))
        now = 1_000
        controller.reconcile(store.bindings.value, views(store, false))
        now = 31_001
        controller.reconcile(store.bindings.value, views(store, false))
        assertEquals(listOf("b1" to "netbird", "b1" to "easytier"), started)
        assertEquals(listOf("b1"), movedOver)
    }

    @Test
    fun aChannelBackInTimeMovesNothing() {
        val (controller, store) = setUp()
        controller.setWanted("b1", true)
        controller.reconcile(store.bindings.value, views(store, true))
        now = 1_000
        controller.reconcile(store.bindings.value, views(store, false))
        now = 20_000
        controller.reconcile(store.bindings.value, views(store, true))
        now = 60_000
        controller.reconcile(store.bindings.value, views(store, true))
        assertEquals(listOf("b1" to "netbird"), started)
    }

    @Test
    fun pickingAnotherNetworkMovesToIt() {
        val (controller, store) = setUp()
        controller.setWanted("b1", true)
        controller.reconcile(store.bindings.value, views(store, true))
        controller.pick("b1", "easytier")
        controller.reconcile(store.bindings.value, views(store, true))
        assertEquals(listOf("b1" to "netbird", "b1" to "easytier"), started)
        assertEquals("easytier", store.get("b1")?.overlayChoice)
    }

    @Test
    fun droppingTheWishStopsTheNetwork() {
        val (controller, store) = setUp()
        controller.setWanted("b1", true)
        controller.reconcile(store.bindings.value, views(store, true))
        controller.setWanted("b1", false)
        controller.reconcile(store.bindings.value, views(store, true))
        assertEquals(1, stops)
    }

    @Test
    fun aRevokedVpnClearsEveryWish() {
        val (controller, store) = setUp()
        controller.setWanted("b1", true)
        controller.reconcile(store.bindings.value, views(store, true))
        controller.revoked()
        assertFalse(store.get("b1")!!.isOverlayWanted)
        assertNull(controller.status.value)
    }

    @Test
    fun aReportFromAnEngineThatNoLongerRunsIsDropped() {
        val (controller, store) = setUp()
        controller.setWanted("b1", true)
        controller.reconcile(store.bindings.value, views(store, true))
        controller.report(OverlayStatus("b1", "easytier", OverlayPhase.ON, "10.0.0.2"))
        assertEquals(OverlayPhase.JOINING, controller.status.value?.phase)
        controller.report(OverlayStatus("b1", "netbird", OverlayPhase.ON, "100.72.4.9"))
        assertEquals("100.72.4.9", controller.status.value?.address)
    }
}
