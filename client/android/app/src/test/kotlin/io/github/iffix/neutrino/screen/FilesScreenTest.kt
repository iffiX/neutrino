package io.github.iffix.neutrino.screen

import io.github.iffix.neutrino.channel.ChannelServiceEntry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class FilesScreenTest {
    private fun share(isHealthy: Boolean?) = ChannelServiceEntry("smb_s1", "file", "lab_share", isHealthy = isHealthy)

    @Test
    fun anUnreachableShareSaysWhyOpenInFilesIsDisabled() {
        assertEquals("ui.reason.unhealthy", openInFilesReasonKey(share(isHealthy = false)))
    }

    @Test
    fun aReachableOrUnprobedShareHasNoReason() {
        assertNull(openInFilesReasonKey(share(isHealthy = true)))
        assertNull(openInFilesReasonKey(share(isHealthy = null)))
    }
}
