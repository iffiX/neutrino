package io.github.iffix.neutrino

/** The languages every screen offers, as the desktop client names them. */
val CLIENT_LANGUAGES: List<String> = listOf("en", "zh-CN")

/** The language used when the phone's own is none of [CLIENT_LANGUAGES]. */
const val CLIENT_DEFAULT_LANGUAGE = "en"

/** The palettes the app draws itself in; `system` follows the phone. */
val CLIENT_THEMES: List<String> = listOf("system", "dark", "light")

/** The palette a fresh install draws in. */
const val CLIENT_DEFAULT_THEME = "system"

/** Past this width, in dp, a landscape window shows the sidebar instead of the bottom bar. */
const val CLIENT_SIDEBAR_MIN_WIDTH_DP = 880

/** The file the language and the theme are kept in. */
const val CLIENT_SETTINGS_FILE_NAME = "client_settings"

/** The language's key in [CLIENT_SETTINGS_FILE_NAME]. */
const val CLIENT_SETTINGS_KEY_LANGUAGE = "language"

/** The theme's key in [CLIENT_SETTINGS_FILE_NAME]. */
const val CLIENT_SETTINGS_KEY_THEME = "theme"

/** Where the desktop client's word catalogs land inside the app's assets. */
const val CLIENT_DESKTOP_LOCALES_DIR = "locales/desktop"

/** Where the app's own word catalogs live inside its assets. */
const val CLIENT_APP_LOCALES_DIR = "locales/app"

/** The edge of the box every icon's path data is drawn in. */
const val ICON_VIEWBOX = 24f

/** The width of an icon's stroke, in units of [ICON_VIEWBOX]. */
const val ICON_STROKE_WIDTH = 1.6f

/** The cores the app carries, as name, version and licence, for the About screen. */
val CLIENT_CARRIED_CORES: List<Triple<String, String, String>> = listOf(
    Triple("NetBird", "0.78.1", "BSD-3-Clause"),
    Triple("EasyTier", "2.6.4", "LGPL-3.0"),
    Triple("RustDesk", "1.4.9", "AGPL-3.0"),
)
