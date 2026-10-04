package io.github.iffix.neutrino.screen

import io.github.iffix.neutrino.RepositoryFiles
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class LocalPortDialogTest {
    @Test
    fun aNumberOutOfRangeDisablesSaveWithTheRangeAsItsReason() {
        assertEquals("ui.reason.port_range", localPortReasonKey(isFixed = true, number = "999"))
        assertEquals("ui.reason.port_range", localPortReasonKey(isFixed = true, number = "65536"))
        assertEquals("ui.reason.port_range", localPortReasonKey(isFixed = true, number = ""))
    }

    @Test
    fun autoOrANumberInRangeLeavesSaveEnabled() {
        assertNull(localPortReasonKey(isFixed = false, number = "999"))
        assertNull(localPortReasonKey(isFixed = true, number = "1024"))
        assertNull(localPortReasonKey(isFixed = true, number = "65535"))
    }

    @Test
    fun cancelComesBeforeSave() {
        assertTrue(cancelBeforeSave("LocalPortDialog.kt"))
        assertTrue(cancelBeforeSave("RemoteDesktopDialog.kt"))
        assertTrue(cancelBeforeSave("SettingsScreen.kt"))
    }

    private fun cancelBeforeSave(file: String): Boolean {
        val source = RepositoryFiles.text("client/android/app/src/main/kotlin/io/github/iffix/neutrino/screen/$file")
        val cancel = source.indexOf("words.word(\"ui.cancel\")")
        val save = source.indexOf("words.word(\"ui.save\")")
        return cancel in 0 until save
    }
}
