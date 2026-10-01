package io.github.iffix.neutrino.binding

import io.github.iffix.neutrino.channel.Samples
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class BindingStoreTest {
    @get:Rule
    val folder = TemporaryFolder()

    private val sealer = FakeSecretSealer()

    private fun store() = BindingStore(folder.root.resolve("bindings.sealed"), sealer)

    @Test
    fun aBindingPutIsKeptAcrossAReopen() {
        store().put(Samples.binding)
        assertEquals(listOf(Samples.binding), store().bindings.value)
    }

    @Test
    fun theFileHoldsNoSecretInTheClear() {
        store().put(Samples.binding)
        val bytes = folder.root.resolve("bindings.sealed").readBytes()
        assertFalse(String(bytes, Charsets.ISO_8859_1).contains(Samples.binding.token))
    }

    @Test
    fun aBindingWithTheSameIdIsReplacedWhereItStands() {
        val store = store()
        store.put(Samples.binding)
        store.put(Samples.binding.copy(id = "b2"))
        store.put(Samples.binding.copy(hubName = "Neutrino"))
        assertEquals(listOf("b1", "b2"), store.bindings.value.map { it.id })
        assertEquals("Neutrino", store.get("b1")?.hubName)
    }

    @Test
    fun updateChangesOneAndIgnoresAnUnknownId() {
        val store = store()
        store.put(Samples.binding)
        assertEquals(true, store.update("b1") { it.copy(isOverlayOn = true) }?.isOverlayOn)
        assertNull(store.update("nobody") { it })
        assertEquals(true, store().get("b1")?.isOverlayOn)
    }

    @Test
    fun removeForgetsTheBinding() {
        val store = store()
        store.put(Samples.binding)
        store.remove("b1")
        assertEquals(emptyList<HubBinding>(), store().bindings.value)
    }

    @Test
    fun theMachineIdIsMadeOnceAndKept() {
        val first = store().machineId
        assertEquals(32, first.length)
        assertEquals(first, store().machineId)
    }

    @Test
    fun aFileAnotherKeySealedReadsAsNoBinding() {
        store().put(Samples.binding)
        val other = BindingStore(folder.root.resolve("bindings.sealed"), FakeSecretSealer())
        assertEquals(emptyList<HubBinding>(), other.bindings.value)
    }
}
