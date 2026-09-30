package io.github.iffix.neutrino.words

import io.github.iffix.neutrino.CLIENT_LANGUAGES
import io.github.iffix.neutrino.CLIENT_THEMES
import io.github.iffix.neutrino.RepositoryFiles
import io.github.iffix.neutrino.shell.AppScreen
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class WordCatalogTest {
    private fun desktop(language: String) =
        WordCatalog.flatten(RepositoryFiles.text("client/desktop/frontend/locales/$language.json"))

    private fun app(language: String) =
        WordCatalog.flatten(RepositoryFiles.text("client/android/app/src/main/assets/locales/app/$language.json"))

    private fun catalog(language: String) = WordCatalog(desktop(language) + app(language))

    @Test
    fun flattenJoinsNestedKeysWithDots() {
        val flat = WordCatalog.flatten("""{"ui": {"a": "A", "name": {"en": "English"}}, "code": {"x": "X"}}""")
        assertEquals(mapOf("ui.a" to "A", "ui.name.en" to "English", "code.x" to "X"), flat)
    }

    @Test(expected = IllegalArgumentException::class)
    fun flattenRefusesAnythingButAnObject() {
        WordCatalog.flatten("[1, 2]")
    }

    @Test
    fun wordFillsItsParameters() {
        val words = WordCatalog(mapOf("ui.hub_software" to "runs {software}"))
        assertEquals(
            "runs neutrino_hub/0.5.0",
            words.word("ui.hub_software", mapOf("software" to "neutrino_hub/0.5.0")),
        )
    }

    @Test
    fun aMissingKeyReadsAsItself() {
        assertEquals("ui.nothing", WordCatalog(emptyMap()).word("ui.nothing"))
    }

    @Test
    fun aRefusalIsWordedByItsCodeOrShownAsTheCode() {
        val words = WordCatalog(mapOf("code.client_disabled" to "the hub has switched this client off"))
        assertEquals("the hub has switched this client off", words.refusal("client_disabled"))
        assertEquals("some_new_code", words.refusal("some_new_code"))
    }

    @Test
    fun theAppsKeysAreTheSameInBothLanguages() {
        assertEquals(app("en").keys, app("zh-CN").keys)
    }

    @Test
    fun theAppAddsNoKeyTheDesktopAlreadyHas() {
        for (language in CLIENT_LANGUAGES) {
            val shared = app(language).keys intersect desktop(language).keys
            assertTrue("shared keys in $language: $shared", shared.isEmpty())
        }
    }

    @Test
    fun everyScreenTitleIsWordedInEveryLanguage() {
        for (language in CLIENT_LANGUAGES) {
            val words = catalog(language)
            for (screen in AppScreen.entries) {
                assertTrue("${screen.titleKey} in $language", words.has(screen.titleKey))
            }
        }
    }

    @Test
    fun everyLanguageAndThemeHasItsName() {
        for (language in CLIENT_LANGUAGES) {
            val words = catalog(language)
            for (name in CLIENT_LANGUAGES) assertTrue(words.has("ui.language_name.$name"))
            for (theme in CLIENT_THEMES) assertTrue(words.has("ui.theme_name.$theme"))
        }
    }

    @Test
    fun hasSaysWhetherAKeyIsThere() {
        val words = WordCatalog(mapOf("ui.a" to "A"))
        assertTrue(words.has("ui.a"))
        assertFalse(words.has("ui.b"))
    }
}
