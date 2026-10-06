package io.github.iffix.neutrino.screen

import io.github.iffix.neutrino.CLIENT_LANGUAGES
import io.github.iffix.neutrino.RepositoryFiles
import io.github.iffix.neutrino.words.WordCatalog
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AiScreenTest {
    private val screen =
        RepositoryFiles.text("client/android/app/src/main/kotlin/io/github/iffix/neutrino/screen/AiScreen.kt")

    @Test
    fun anEndpointWithNoPathGivesTheAddressAndTheAddressWithV1() {
        assertEquals(
            listOf("http://127.0.0.1:20317", "http://127.0.0.1:20317/v1"),
            loopbackAddressesOf("http://192.168.10.1:8317", 20317),
        )
        assertEquals(
            listOf("http://127.0.0.1:20317/", "http://127.0.0.1:20317/v1"),
            loopbackAddressesOf("http://192.168.10.1:8317/", 20317),
        )
    }

    @Test
    fun anEndpointPathIsKeptAndV1IsAddedOnlyWhereItIsMissing() {
        assertEquals(
            listOf("http://127.0.0.1:20317/gateway", "http://127.0.0.1:20317/gateway/v1"),
            loopbackAddressesOf("http://hub.lan:8317/gateway", 20317),
        )
        assertEquals(
            listOf("http://127.0.0.1:20317/gateway/v1", "http://127.0.0.1:20317/gateway/v1"),
            loopbackAddressesOf("https://hub.lan/gateway/v1", 20317),
        )
    }

    @Test
    fun eachLineHasItsLabelAndCopiesItsOwnAddress() {
        val forwarded = screen.substringAfter("if (row.isForwarded) {\n            val (plain, withVersion)")
            .substringBefore("\n        when (val current = answer)")
        assertTrue(forwarded.contains("ValueField(words.word(\"ui.ai_address_plain\"), plain) {"))
        assertTrue(forwarded.contains("CopyButton(isEnabled = isFree) { onCopy(plain, false) }"))
        assertTrue(forwarded.contains("ValueField(words.word(\"ui.ai_address_v1\"), withVersion) {"))
        assertTrue(forwarded.contains("CopyButton(isEnabled = isFree) { onCopy(withVersion, false) }"))
        assertTrue(forwarded.indexOf("ui.ai_address_plain") < forwarded.indexOf("ui.ai_address_v1"))
    }

    @Test
    fun theHiddenKeyShowsNoneOfTheKey() {
        val key = "sk-nt-7f3a9c21e4b84d06"
        val hidden = shownKey(key, isShown = false)
        assertEquals("•".repeat(16), hidden)
        assertEquals(hidden, shownKey("ab", isShown = false))
        assertTrue(hidden.none { it in key })
        assertEquals(key, shownKey(key, isShown = true))
    }

    @Test
    fun theLabelsAreWordedInEveryLanguage() {
        val expected = mapOf(
            "en" to listOf("For apps that add /v1 themselves", "For apps that want /v1 in the address"),
            "zh-CN" to listOf("应用自己会加 /v1 时用这个", "应用要求地址带 /v1 时用这个"),
        )
        for (language in CLIENT_LANGUAGES) {
            val words = WordCatalog(
                WordCatalog.flatten(RepositoryFiles.text("client/desktop/frontend/locales/$language.json")) +
                    WordCatalog.flatten(
                        RepositoryFiles.text("client/android/app/src/main/assets/locales/app/$language.json"),
                    ),
            )
            assertEquals(expected[language], listOf(words.word("ui.ai_address_plain"), words.word("ui.ai_address_v1")))
        }
    }
}
