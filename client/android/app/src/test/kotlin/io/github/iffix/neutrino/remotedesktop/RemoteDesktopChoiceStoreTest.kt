package io.github.iffix.neutrino.remotedesktop

import io.github.iffix.neutrino.CLIENT_SETTINGS_KEY_RDP_CHOICES
import io.github.iffix.neutrino.FakeSharedPreferences
import org.junit.Assert.assertEquals
import org.junit.Test

class RemoteDesktopChoiceStoreTest {
    private val preferences = FakeSharedPreferences()

    @Test
    fun anEntryNeverConfiguredIsAutoAndBalanced() {
        assertEquals(RemoteDesktopChoice(), RemoteDesktopChoiceStore(preferences).get("b1/r1"))
    }

    @Test
    fun aChoiceIsKeptPerEntryAndAfterARestart() {
        val store = RemoteDesktopChoiceStore(preferences)
        store.put("b1/r1", RemoteDesktopChoice(RemoteDesktopCodec.H264, RemoteDesktopQuality.LOW))
        store.put("b1/r2", RemoteDesktopChoice(RemoteDesktopCodec.VP9, RemoteDesktopQuality.BEST))
        val again = RemoteDesktopChoiceStore(preferences)
        assertEquals(RemoteDesktopChoice(RemoteDesktopCodec.H264, RemoteDesktopQuality.LOW), again.get("b1/r1"))
        assertEquals(RemoteDesktopChoice(RemoteDesktopCodec.VP9, RemoteDesktopQuality.BEST), again.get("b1/r2"))
    }

    @Test
    fun aNameTheAppDoesNotKnowFallsBackToTheDefault() {
        preferences.values[CLIENT_SETTINGS_KEY_RDP_CHOICES] = """{"b1/r1":{"codec":"mpeg2","quality":"ultra"}}"""
        assertEquals(RemoteDesktopChoice(), RemoteDesktopChoiceStore(preferences).get("b1/r1"))
    }

    @Test
    fun unreadableSettingsAreNoChoice() {
        preferences.values[CLIENT_SETTINGS_KEY_RDP_CHOICES] = "not json"
        assertEquals(RemoteDesktopChoice(), RemoteDesktopChoiceStore(preferences).get("b1/r1"))
    }

    @Test
    fun leavingAHubDropsItsChoices() {
        val store = RemoteDesktopChoiceStore(preferences)
        store.put("b1/r1", RemoteDesktopChoice(RemoteDesktopCodec.AV1))
        store.put("b2/r1", RemoteDesktopChoice(RemoteDesktopCodec.AV1))
        store.forget("b1")
        assertEquals(RemoteDesktopChoice(), RemoteDesktopChoiceStore(preferences).get("b1/r1"))
        assertEquals(RemoteDesktopCodec.AV1, RemoteDesktopChoiceStore(preferences).get("b2/r1").codec)
    }
}
