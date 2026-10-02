package io.github.iffix.neutrino.files

import java.io.IOException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class ShareFileTest {
    private val opens = mutableListOf<Boolean>()
    private val links = mutableListOf<FakeLink>()
    private var failures = 0

    private val file = ShareFile { isAgain ->
        opens += isAgain
        FakeLink().also { links += it }
    }

    @Test
    fun aReadThatFailsOpensTheFileAgainAndReadsOnce() {
        failures = 1
        val data = ByteArray(4)
        assertEquals(4, file.read(8, data, 4))
        assertEquals(listOf(false, true), opens)
        assertTrue(links.first().isClosed)
        assertEquals(8L, links.last().offsets.single())
    }

    @Test
    fun aWriteThatFailsReopensWithoutEmptyingTheFile() {
        failures = 1
        file.write(0, ByteArray(2), 2)
        assertEquals(listOf(false, true), opens)
        assertEquals(1, links.last().writes)
    }

    @Test
    fun aSecondFailureReachesTheCaller() {
        failures = 2
        try {
            file.read(0, ByteArray(1), 1)
            fail("the second failure was swallowed")
        } catch (_: IOException) {
            // Only one retry.
        }
        assertEquals(2, opens.size)
    }

    @Test
    fun theSizeIsTheFirstOpensAndCloseClosesTheLink() {
        assertEquals(42L, file.size)
        file.close()
        assertTrue(links.single().isClosed)
    }

    private inner class FakeLink : ShareFileLink {
        val offsets = mutableListOf<Long>()
        var writes = 0
        var isClosed = false
        override val size: Long = 42

        override fun read(offset: Long, data: ByteArray, count: Int): Int {
            fail()
            offsets += offset
            return count
        }

        override fun write(offset: Long, data: ByteArray, count: Int) {
            fail()
            writes += 1
        }

        override fun close() {
            isClosed = true
        }

        private fun fail() {
            if (failures > 0) {
                failures -= 1
                throw IOException("connection reset")
            }
        }
    }
}
