package io.github.iffix.neutrino.settings

import io.github.iffix.neutrino.CLIENT_DEFAULT_LANGUAGE
import io.github.iffix.neutrino.CLIENT_DEFAULT_THEME
import io.github.iffix.neutrino.CLIENT_LANGUAGES
import io.github.iffix.neutrino.CLIENT_THEMES

/**
 * What a person chose on the settings screen.
 *
 * @property language One of [CLIENT_LANGUAGES].
 * @property theme One of [CLIENT_THEMES].
 */
data class ClientSettings(val language: String, val theme: String) {
    /** The same settings with any value outside its list replaced by the default. */
    fun cleaned(): ClientSettings = ClientSettings(
        language = language.takeIf { it in CLIENT_LANGUAGES } ?: CLIENT_DEFAULT_LANGUAGE,
        theme = theme.takeIf { it in CLIENT_THEMES } ?: CLIENT_DEFAULT_THEME,
    )

    companion object {
        /**
         * The settings of a fresh install on a phone speaking [phoneLanguage].
         *
         * @param phoneLanguage The phone's language tag, such as `zh-CN` or `en-US`.
         * @return Chinese for a Chinese phone, else the default language, with the default theme.
         */
        fun fresh(phoneLanguage: String): ClientSettings {
            val language = if (phoneLanguage.startsWith("zh")) "zh-CN" else CLIENT_DEFAULT_LANGUAGE
            return ClientSettings(language = language, theme = CLIENT_DEFAULT_THEME)
        }
    }
}
