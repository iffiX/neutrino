package io.github.iffix.neutrino.files

import org.junit.Assert.assertEquals
import org.junit.Test

class ShareOpenModeTest {
    @Test
    fun onlyTheModesThatEmptyAFileEmptyIt() {
        assertEquals(ShareOpenMode(isRead = true, isWrite = false, isTruncate = false), ShareOpenMode.parse("r"))
        assertEquals(ShareOpenMode(isRead = false, isWrite = true, isTruncate = true), ShareOpenMode.parse("w"))
        assertEquals(ShareOpenMode(isRead = false, isWrite = true, isTruncate = true), ShareOpenMode.parse("wt"))
        assertEquals(ShareOpenMode(isRead = false, isWrite = true, isTruncate = false), ShareOpenMode.parse("wa"))
        assertEquals(ShareOpenMode(isRead = true, isWrite = true, isTruncate = false), ShareOpenMode.parse("rw"))
        assertEquals(ShareOpenMode(isRead = true, isWrite = true, isTruncate = true), ShareOpenMode.parse("rwt"))
    }

    @Test(expected = IllegalArgumentException::class)
    fun anUnknownModeIsRefused() {
        ShareOpenMode.parse("x")
    }
}
