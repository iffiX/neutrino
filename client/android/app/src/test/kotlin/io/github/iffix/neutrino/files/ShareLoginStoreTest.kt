package io.github.iffix.neutrino.files

import io.github.iffix.neutrino.binding.FakeSecretSealer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class ShareLoginStoreTest {
    @get:Rule
    val folder = TemporaryFolder()

    private val sealer = FakeSecretSealer()

    private fun store() = ShareLoginStore(folder.root.resolve("shares.sealed"), sealer)

    @Test
    fun aKeptLoginOutlivesTheRunSealed() {
        store().put("r1", ShareLogin("iffi", "secret"), isKept = true)
        assertEquals(ShareLogin("iffi", "secret"), store().get("r1"))
        assertFalse(String(folder.root.resolve("shares.sealed").readBytes(), Charsets.ISO_8859_1).contains("secret"))
    }

    @Test
    fun aLoginForThisRunIsNotWritten() {
        val store = store()
        store.put("r1", ShareLogin("iffi", "secret"), isKept = false)
        assertEquals("secret", store.get("r1")?.password)
        assertFalse(store.isKept("r1"))
        assertNull(store().get("r1"))
    }

    @Test
    fun forgettingDropsBoth() {
        val store = store()
        store.put("r1", ShareLogin("iffi", "a"), isKept = true)
        assertTrue(store.isKept("r1"))
        store.forget("r1")
        assertNull(store.get("r1"))
        assertNull(store().get("r1"))
    }
}
