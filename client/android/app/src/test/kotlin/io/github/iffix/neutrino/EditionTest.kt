package io.github.iffix.neutrino

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class EditionTest {
    private val sources = "client/android/app/src"

    // Each feature's own packages: its part's and its core's.
    private val featurePackages = mapOf(
        EDITION_FEATURE_NETBIRD to listOf("io.github.iffix.neutrino.netbird", "io.netbird"),
    )

    @Test
    fun theBuildNamesTheEditionTheRootFileNames() {
        assertEquals(RepositoryFiles.text("EDITION").trim(), BuildConfig.EDITION)
        assertEquals(CLIENT_SOURCE_URLS.getValue(BuildConfig.EDITION), Edition.sourceUrl)
    }

    @Test
    fun aFeatureIsPresentExactlyWhenItsOwnSourcesAre() {
        for ((feature, className) in EDITION_FEATURE_PARTS) {
            val part = RepositoryFiles.file("$sources/$feature/kotlin/${className.replace('.', '/')}.kt")
            assertEquals(feature, part.isFile, Edition.hasFeature(feature))
            assertEquals(feature, part.isFile, Edition.overlayParts.any { it.javaClass.name == className })
        }
    }

    @Test
    fun noSourceOutsideAFeatureImportsIt() {
        val found = listOf("main", "test").flatMap { set ->
            RepositoryFiles.file("$sources/$set").walkTopDown().filter { it.extension == "kt" }.filter { file ->
                val text = file.readText()
                featurePackages.values.flatten().any { text.contains("import $it.") }
            }.map { it.name }.toList()
        }
        assertEquals(emptyList<String>(), found)
    }

    @Test
    fun theMainlandTreeLeavesOutEachFeaturesOwnSources() {
        val listed = RepositoryFiles.text("packaging/shared/constants.py")
        for (feature in EDITION_FEATURE_PARTS.keys) {
            assertTrue(feature, listed.contains("\"$sources/$feature\""))
            assertTrue(feature, listed.contains("\"$sources/test_$feature\""))
        }
    }

    @Test
    fun theCarriedCoresAreThePresentFeaturesThenEveryEditions() {
        assertEquals(Edition.overlayParts.map { it.carriedCore } + CLIENT_CARRIED_CORES, Edition.carriedCores)
    }

    @Test
    fun anUnknownFeatureIsRefused() {
        assertThrows(IllegalArgumentException::class.java) { Edition.hasFeature("no_such_feature") }
    }
}
