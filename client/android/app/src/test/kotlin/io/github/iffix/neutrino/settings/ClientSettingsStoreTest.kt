package io.github.iffix.neutrino.settings

import io.github.iffix.neutrino.FakeSharedPreferences
import org.junit.Assert.assertEquals
import org.junit.Test

class ClientSettingsStoreTest {
    @Test
    fun aFreshStoreFollowsThePhonesLanguage() {
        val store = ClientSettingsStore(FakeSharedPreferences(), phoneLanguage = "zh-CN")
        assertEquals(ClientSettings("zh-CN", "system"), store.settings.value)
    }

    @Test
    fun savedSettingsAreInForceAndKept() {
        val preferences = FakeSharedPreferences()
        ClientSettingsStore(preferences, phoneLanguage = "en").save(ClientSettings("zh-CN", "light"))
        val again = ClientSettingsStore(preferences, phoneLanguage = "en")
        assertEquals(ClientSettings("zh-CN", "light"), again.settings.value)
    }

    @Test
    fun aSavedValueOutsideItsListIsKeptAsTheDefault() {
        val store = ClientSettingsStore(FakeSharedPreferences(), phoneLanguage = "en")
        store.save(ClientSettings("xx", "neon"))
        assertEquals(ClientSettings("en", "system"), store.settings.value)
    }
}
