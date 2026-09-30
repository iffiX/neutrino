package io.github.iffix.neutrino.files

import org.junit.Assert.assertEquals
import org.junit.Test

class ShareDocumentIdTest {
    @Test
    fun anIdIsTheRootThenThePath() {
        val document = ShareDocumentId("b1~f1", "").child("docs").child("a b.txt")
        assertEquals("b1~f1/docs/a b.txt", document.encoded)
        assertEquals(document, ShareDocumentId.decode(document.encoded))
    }

    @Test
    fun theShareItselfHasAnEmptyPath() {
        assertEquals(ShareDocumentId("b1~f1", ""), ShareDocumentId.decode("b1~f1/"))
    }

    @Test
    fun smbSpellsThePathWithBackslashes() {
        assertEquals("docs\\a.txt", ShareDocumentId("r", "docs/a.txt").smbPath)
        assertEquals("a.txt", ShareDocumentId("r", "docs/a.txt").name)
    }

    @Test(expected = IllegalArgumentException::class)
    fun anIdWithoutARootIsRefused() {
        ShareDocumentId.decode("/docs")
    }
}
