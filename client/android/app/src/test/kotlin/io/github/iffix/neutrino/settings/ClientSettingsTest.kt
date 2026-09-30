package io.github.iffix.neutrino.settings

import org.junit.Assert.assertEquals
import org.junit.Test

class ClientSettingsTest {
    @Test
    fun aChinesePhoneStartsInChinese() {
        assertEquals(ClientSettings("zh-CN", "system"), ClientSettings.fresh("zh-Hans-CN"))
    }

    @Test
    fun anyOtherPhoneStartsInEnglish() {
        assertEquals(ClientSettings("en", "system"), ClientSettings.fresh("de-DE"))
    }

    @Test
    fun aValueOutsideItsListBecomesTheDefault() {
        assertEquals(ClientSettings("en", "system"), ClientSettings("fr", "neon").cleaned())
    }

    @Test
    fun aValueInsideItsListIsKept() {
        assertEquals(ClientSettings("zh-CN", "light"), ClientSettings("zh-CN", "light").cleaned())
    }
}
