package io.github.iffix.neutrino

import org.junit.Assert.assertEquals
import org.junit.Test

class ConstantsTest {
    private fun pinnedTag(script: String, name: String): String {
        val text = RepositoryFiles.text("packaging/$script")
        return Regex("""$name = "v?([0-9.]+)"""").find(text)?.groupValues?.get(1)
            ?: throw AssertionError("$script pins no $name")
    }

    @Test
    fun theAboutScreenNamesTheCoresTheBuildScriptsPin() {
        val versions = CLIENT_CARRIED_CORES.associate { (name, version, _) -> name to version }
        assertEquals(pinnedTag("build/build_core_netbird.py", "NETBIRD_MOBILE_TAG"), versions["NetBird"])
        assertEquals(pinnedTag("build/build_core_easytier.py", "EASYTIER_MOBILE_TAG"), versions["EasyTier"])
        assertEquals(pinnedTag("build/build_core_rustdesk.py", "RUSTDESK_MOBILE_TAG"), versions[CLIENT_RUSTDESK_CORE])
    }

    @Test
    fun theRustDeskSourceLinkNamesThePinnedTag() {
        val tag = pinnedTag("build/build_core_rustdesk.py", "RUSTDESK_MOBILE_TAG")
        assertEquals("https://github.com/rustdesk/rustdesk/tree/$tag", CLIENT_RUSTDESK_SOURCE_URL)
    }

    @Test
    fun everyCoreLinksItsPinnedSourceAndPatch() {
        val netbird = CLIENT_CARRIED_CORES.single { it.name == "NetBird" }
        val easytier = CLIENT_CARRIED_CORES.single { it.name == "EasyTier" }
        val rustdesk = CLIENT_CARRIED_CORES.single { it.name == CLIENT_RUSTDESK_CORE }
        assertEquals("https://github.com/netbirdio/netbird/tree/v${netbird.version}", netbird.sourceUrl)
        assertEquals("https://github.com/EasyTier/EasyTier/tree/v${easytier.version}", easytier.sourceUrl)
        assertEquals(CLIENT_RUSTDESK_SOURCE_URL, rustdesk.sourceUrl)
        assertEquals("https://gitee.com/easytier/EasyTier/tree/v${easytier.version}", easytier.mainlandSourceUrl)
        assertEquals("https://gitee.com/mirrors/rustdesk/tree/${rustdesk.version}", rustdesk.mainlandSourceUrl)
        for (core in CLIENT_CARRIED_CORES) {
            val expected = if (Edition.current == EDITION_CN && core.mainlandSourceUrl.isNotEmpty()) {
                core.mainlandSourceUrl
            } else {
                core.sourceUrl
            }
            assertEquals(core.name, expected, Edition.sourceUrlOf(core))
            val patch = "packaging/build/build_core_${core.name.lowercase()}.patch"
            val hasPatch = RepositoryFiles.file(patch).exists()
            assertEquals(core.name, hasPatch, core.patchUrl.isNotEmpty())
            if (hasPatch) assertEquals("{blob}/v{version}/$patch", core.patchUrl)
        }
    }

    @Test
    fun theAboutScreenNamesTheTransportsGoModulesAtTheVersionsGoModPins() {
        val goMod = RepositoryFiles.text("transport/go.mod")
        for (module in CLIENT_TRANSPORT_MODULES) {
            val path = if (module.name.startsWith("golang.org/")) module.name else "github.com/${module.name}"
            val pinned = Regex("""(?m)^\s*$path(?:/v\d+)? v([0-9.]+)""").find(goMod)?.groupValues?.get(1)
            assertEquals(module.name, pinned, module.version)
            assertEquals(module.name, true, module.sourceUrl.endsWith("v${module.version}"))
        }
    }

    @Test
    fun theDesktopTimingsAreTheSame() {
        val desktop = RepositoryFiles.text("client/desktop/neutrino_client/constants.py")
        for ((name, value) in listOf(
            "CLIENT_BACKOFF_MIN_S" to CLIENT_BACKOFF_MIN_S,
            "CLIENT_BACKOFF_MAX_S" to CLIENT_BACKOFF_MAX_S,
            "CLIENT_CONNECT_TIMEOUT_S" to CLIENT_CONNECT_TIMEOUT_S,
            "CLIENT_REPORT_INTERVAL_S" to CLIENT_REPORT_INTERVAL_S,
            "CLIENT_STREAM_TIMEOUT_S" to CLIENT_STREAM_TIMEOUT_S,
        )) {
            val pinned = Regex("""(?m)^$name = (\d+)""").find(desktop)?.groupValues?.get(1)?.toLong()
            assertEquals(name, pinned, value)
        }
    }
}
