package io.github.iffix.neutrino.settings

import android.content.SharedPreferences
import androidx.core.content.edit
import io.github.iffix.neutrino.CLIENT_SETTINGS_KEY_LANGUAGE
import io.github.iffix.neutrino.CLIENT_SETTINGS_KEY_THEME
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * The language and the theme, kept on the phone and watched by every screen.
 *
 * @param preferences Where the two values are written.
 * @param phoneLanguage The phone's language tag, which picks the language of a fresh install.
 */
class ClientSettingsStore(private val preferences: SharedPreferences, phoneLanguage: String) {
    private val fresh = ClientSettings.fresh(phoneLanguage)
    private val current = MutableStateFlow(read())

    /** The settings in force. */
    val settings: StateFlow<ClientSettings> = current.asStateFlow()

    /**
     * Keep new settings and put them in force.
     *
     * @param settings What the person saved; a value outside its list becomes the default.
     */
    fun save(settings: ClientSettings) {
        val cleaned = settings.cleaned()
        preferences.edit {
            putString(CLIENT_SETTINGS_KEY_LANGUAGE, cleaned.language)
            putString(CLIENT_SETTINGS_KEY_THEME, cleaned.theme)
        }
        current.value = cleaned
    }

    private fun read(): ClientSettings = ClientSettings(
        language = preferences.getString(CLIENT_SETTINGS_KEY_LANGUAGE, null) ?: fresh.language,
        theme = preferences.getString(CLIENT_SETTINGS_KEY_THEME, null) ?: fresh.theme,
    ).cleaned()
}
