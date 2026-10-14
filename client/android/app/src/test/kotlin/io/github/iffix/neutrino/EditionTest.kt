package io.github.iffix.neutrino

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class EditionTest {
    @Test
    fun theBuildNamesTheEditionTheRootFileNames() {
        assertEquals(RepositoryFiles.text("EDITION").trim(), BuildConfig.EDITION)
        assertEquals(CLIENT_SOURCE_URLS.getValue(BuildConfig.EDITION), Edition.sourceUrl)
    }

    @Test
    fun theMainlandTreeLeavesOutNoSourceOfTheApp() {
        val listed = RepositoryFiles.text("packaging/shared/constants.py")
        assertFalse(listed.contains("\"client/android/"))
        assertFalse(listed.contains("\"packaging/build/build_core_netbird.py\""))
    }

    @Test
    fun netBirdIsInTheMainSourceSet() {
        val sources = RepositoryFiles.file("client/android/app/src")
        assertTrue(sources.resolve("main/kotlin/io/github/iffix/neutrino/netbird/NetbirdOverlayEngine.kt").isFile)
        assertEquals(listOf("main", "test"), sources.list()?.sorted())
    }
}
