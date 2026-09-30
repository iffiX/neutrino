package io.github.iffix.neutrino

import org.junit.Assert.assertEquals
import org.junit.Test

class ConstantsTest {
    private fun pinnedTag(script: String, name: String): String {
        val text = RepositoryFiles.text("packaging/$script")
        return Regex("""$name = "v([0-9.]+)"""").find(text)?.groupValues?.get(1)
            ?: throw AssertionError("$script pins no $name")
    }

    @Test
    fun theAboutScreenNamesTheCoresTheBuildScriptsPin() {
        val versions = CLIENT_CARRIED_CORES.associate { (name, version, _) -> name to version }
        assertEquals(pinnedTag("mobile_netbird.py", "NETBIRD_MOBILE_TAG"), versions["NetBird"])
        assertEquals(pinnedTag("mobile_easytier.py", "EASYTIER_MOBILE_TAG"), versions["EasyTier"])
    }

    @Test
    fun theDesktopTimingsAreTheSame() {
        val desktop = RepositoryFiles.text("client/desktop/neutrino_client/constants.py")
        for ((name, value) in listOf(
            "CLIENT_BACKOFF_MIN_S" to CLIENT_BACKOFF_MIN_S,
            "CLIENT_BACKOFF_MAX_S" to CLIENT_BACKOFF_MAX_S,
            "CLIENT_ROTATE_DELAY_S" to CLIENT_ROTATE_DELAY_S,
            "CLIENT_WS_SILENCE_TIMEOUT_S" to CLIENT_WS_SILENCE_TIMEOUT_S,
            "CLIENT_CONNECT_TIMEOUT_S" to CLIENT_CONNECT_TIMEOUT_S,
            "CLIENT_REPORT_INTERVAL_S" to CLIENT_REPORT_INTERVAL_S,
            "CLIENT_STREAM_TIMEOUT_S" to CLIENT_STREAM_TIMEOUT_S,
        )) {
            val pinned = Regex("""(?m)^$name = (\d+)""").find(desktop)?.groupValues?.get(1)?.toLong()
            assertEquals(name, pinned, value)
        }
    }
}
