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

    @Test
    fun aTakenNameIsNumberedBeforeItsExtensionAndTheTakenFileKeepsItsBytes() {
        val share = mutableMapOf("docs/hello.txt" to "hello, world".toByteArray())
        val made = ShareDocumentId("r", "docs/hello.txt").makeFree(false, 32) { candidate ->
            share.putIfAbsent(candidate.path, ByteArray(0)) == null
        }
        assertEquals(ShareDocumentId("r", "docs/hello (1).txt"), made)
        assertEquals("hello, world", String(share.getValue("docs/hello.txt")))
        assertEquals(0, share.getValue("docs/hello (1).txt").size)
    }

    @Test
    fun aCopyIntoItsOwnFolderIsASecondFileWithTheBytes() {
        val share = mutableMapOf("hello.txt" to "hello, world".toByteArray(), "hello (1).txt" to ByteArray(1))
        val source = ShareDocumentId("r", "hello.txt")
        val copy = ShareDocumentId("r", "").child(source.name).makeFree(false, 32) {
            share.putIfAbsent(it.path, ByteArray(0)) == null
        }
        share[copy.path] = share.getValue(source.path).copyOf()
        assertEquals("hello (2).txt", copy.path)
        assertEquals("hello, world", String(share.getValue("hello.txt")))
        assertEquals("hello, world", String(share.getValue("hello (2).txt")))
    }

    @Test
    fun aFolderOrANameWithoutExtensionIsNumberedAtItsEnd() {
        val taken = setOf("a.b", "notes", ".profile")
        val folder = ShareDocumentId("r", "a.b").makeFree(true, 32) { it.path !in taken }
        val plain = ShareDocumentId("r", "notes").makeFree(false, 32) { it.path !in taken }
        val hidden = ShareDocumentId("r", ".profile").makeFree(false, 32) { it.path !in taken }
        assertEquals(listOf("a.b (1)", "notes (1)", ".profile (1)"), listOf(folder.path, plain.path, hidden.path))
    }

    @Test(expected = java.nio.file.FileAlreadyExistsException::class)
    fun everyNameTakenIsRefusedAndNothingIsReplaced() {
        ShareDocumentId("r", "hello.txt").makeFree(false, 3) { false }
    }

    @Test(expected = IllegalArgumentException::class)
    fun anIdWithoutARootIsRefused() {
        ShareDocumentId.decode("/docs")
    }
}
