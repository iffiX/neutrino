package io.github.iffix.neutrino.channel

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ShortEnrollmentLinkTest {
    @Test
    fun aShortLinkSplitsIntoItsTicketAddressAndFingerprint() {
        val parsed = ShortEnrollmentLink.parse("neutrino://enroll/Tk_-9@192.168.100.1:8443/" + "AB".repeat(32))
        assertEquals(
            ChannelResult.Ok(ShortEnrollmentLink("Tk_-9", "https://192.168.100.1:8443", "ab".repeat(32))),
            parsed,
        )
    }

    @Test
    fun theAtSignTellsAShortLinkFromALongOne() {
        assertTrue(ShortEnrollmentLink.isShort("neutrino://enroll/t@192.168.100.1:8443/" + Samples.FINGERPRINT))
        assertFalse(ShortEnrollmentLink.isShort(Samples.link(Samples.clientPayload)))
    }

    @Test
    fun aShortLinkMissingAPartIsUnreadable() {
        val broken = listOf(
            "@192.168.100.1:8443/" + Samples.FINGERPRINT,
            "t@192.168.100.1/" + Samples.FINGERPRINT,
            "t@192.168.100.1:8443/" + "ab".repeat(31),
            "t@192.168.100.1:8443/" + "zz".repeat(32),
            "t@:8443/" + Samples.FINGERPRINT,
        )
        for (text in broken) {
            assertEquals(text, "link_unreadable", (ShortEnrollmentLink.parse(text) as ChannelResult.Refused).code)
        }
    }
}
