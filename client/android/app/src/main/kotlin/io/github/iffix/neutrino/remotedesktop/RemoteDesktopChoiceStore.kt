package io.github.iffix.neutrino.remotedesktop

import android.content.SharedPreferences
import androidx.core.content.edit
import io.github.iffix.neutrino.CLIENT_SETTINGS_KEY_RDP_CHOICES
import kotlinx.serialization.SerializationException
import kotlinx.serialization.builtins.MapSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.Json

/**
 * Each shared desktop's codec and quality, by entry key `<binding>/<entry>`, kept in the app's
 * settings as the core's names.
 *
 * @param preferences Where the choices are written.
 */
class RemoteDesktopChoiceStore(private val preferences: SharedPreferences) {
    private var current: Map<String, Map<String, String>> = read()

    /**
     * One entry's choice.
     *
     * @param key The entry's key.
     * @return The kept choice, or Auto and Balanced for an entry never configured.
     */
    fun get(key: String): RemoteDesktopChoice = synchronized(this) {
        val kept = current[key] ?: return RemoteDesktopChoice()
        RemoteDesktopChoice(
            codec = RemoteDesktopCodec.of(kept[FIELD_CODEC].orEmpty()),
            quality = RemoteDesktopQuality.of(kept[FIELD_QUALITY].orEmpty()),
        )
    }

    /**
     * Keep one entry's choice.
     *
     * @param key The entry's key.
     * @param choice The choice.
     */
    fun put(key: String, choice: RemoteDesktopChoice) = synchronized(this) {
        write(current + (key to mapOf(FIELD_CODEC to choice.codec.coreName, FIELD_QUALITY to choice.quality.coreName)))
    }

    /**
     * A hub is left: its entries' choices go.
     *
     * @param bindingId The hub.
     */
    fun forget(bindingId: String) = synchronized(this) {
        write(current.filterKeys { !it.startsWith("$bindingId/") })
    }

    private fun write(choices: Map<String, Map<String, String>>) {
        preferences.edit { putString(CLIENT_SETTINGS_KEY_RDP_CHOICES, json.encodeToString(serializer, choices)) }
        current = choices
    }

    private fun read(): Map<String, Map<String, String>> {
        val text = preferences.getString(CLIENT_SETTINGS_KEY_RDP_CHOICES, null) ?: return emptyMap()
        return try {
            json.decodeFromString(serializer, text)
        } catch (_: SerializationException) {
            emptyMap()
        } catch (_: IllegalArgumentException) {
            emptyMap()
        }
    }

    private companion object {
        const val FIELD_CODEC = "codec"
        const val FIELD_QUALITY = "quality"
        val json = Json { ignoreUnknownKeys = true }
        val serializer = MapSerializer(String.serializer(), MapSerializer(String.serializer(), String.serializer()))
    }
}
