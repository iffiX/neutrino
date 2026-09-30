package io.github.iffix.neutrino.words

import android.content.res.AssetManager
import io.github.iffix.neutrino.CLIENT_APP_LOCALES_DIR
import io.github.iffix.neutrino.CLIENT_DESKTOP_LOCALES_DIR
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject

/**
 * Every sentence a screen shows in one language, by the dotted key the desktop client uses.
 *
 * The desktop client's catalog is read first and the app's own on top of it; the two hold no
 * key in common. A key with no sentence reads as the key itself.
 *
 * @param words The sentences by key, `{name}` marking where a parameter goes.
 */
class WordCatalog(private val words: Map<String, String>) {
    /** Every key the catalog holds. */
    val keys: Set<String> get() = words.keys

    /**
     * The sentence for one key, its parameters filled in.
     *
     * @param key The dotted key, such as `ui.add_hub`.
     * @param params The values its `{name}` markers take; a marker with no value stays as it is.
     * @return The sentence, or the key when the catalog has none.
     */
    fun word(key: String, params: Map<String, Any?> = emptyMap()): String {
        var sentence = words[key] ?: return key
        for ((name, value) in params) {
            sentence = sentence.replace("{$name}", value?.toString() ?: "")
        }
        return sentence
    }

    /**
     * The sentence for a refusal's code, or the code itself when no sentence names it.
     *
     * @param code The refusal's code.
     * @param params Its parameters.
     * @return The worded refusal.
     */
    fun refusal(code: String, params: Map<String, Any?> = emptyMap()): String {
        val key = "code.$code"
        return if (key in words) word(key, params) else code
    }

    /**
     * Whether the catalog holds a sentence for one key.
     *
     * @param key The dotted key.
     * @return True when the key has a sentence.
     */
    fun has(key: String): Boolean = key in words

    companion object {
        private val json = Json { ignoreUnknownKeys = true }

        /**
         * One catalog file as dotted keys.
         *
         * @param text The file's JSON: nested objects of strings.
         * @return Every string under its dotted path.
         * @throws IllegalArgumentException When the text is not a JSON object.
         */
        fun flatten(text: String): Map<String, String> {
            val root = json.parseToJsonElement(text) as? JsonObject
                ?: throw IllegalArgumentException("a word catalog is a JSON object")
            val flat = linkedMapOf<String, String>()
            collect("", root, flat)
            return flat
        }

        /**
         * The catalog of one language from the app's assets.
         *
         * @param assets The app's assets.
         * @param language One of the client's languages.
         * @return The desktop client's sentences with the app's own on top.
         * @throws java.io.IOException When a catalog file cannot be read.
         */
        fun load(assets: AssetManager, language: String): WordCatalog {
            val desktop = assets.open("$CLIENT_DESKTOP_LOCALES_DIR/$language.json")
                .bufferedReader().use { flatten(it.readText()) }
            val app = assets.open("$CLIENT_APP_LOCALES_DIR/$language.json")
                .bufferedReader().use { flatten(it.readText()) }
            return WordCatalog(desktop + app)
        }

        private fun collect(prefix: String, node: JsonObject, into: MutableMap<String, String>) {
            for ((name, value) in node) {
                val key = if (prefix.isEmpty()) name else "$prefix.$name"
                when (value) {
                    is JsonObject -> collect(key, value.jsonObject, into)
                    is JsonPrimitive -> into[key] = value.content
                    else -> Unit
                }
            }
        }
    }
}
