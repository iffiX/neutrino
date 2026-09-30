package io.github.iffix.neutrino

import android.app.Application
import android.content.Context
import android.os.Build
import android.provider.Settings
import io.github.iffix.neutrino.settings.ClientSettingsStore
import java.util.Locale

/** The app's process: what outlives one screen, made once. */
class NeutrinoApplication : Application() {
    /** The language and the theme. */
    val settingsStore: ClientSettingsStore by lazy {
        ClientSettingsStore(
            preferences = getSharedPreferences(CLIENT_SETTINGS_FILE_NAME, Context.MODE_PRIVATE),
            phoneLanguage = Locale.getDefault().toLanguageTag(),
        )
    }

    /** The name this phone goes by: the one the person gave it, else its model. */
    val deviceName: String
        get() = Settings.Global.getString(contentResolver, Settings.Global.DEVICE_NAME) ?: Build.MODEL

    /** The machine this build runs on, as the hub names architectures. */
    val architecture: String
        get() = when (Build.SUPPORTED_ABIS.firstOrNull()) {
            "arm64-v8a" -> "arm64"
            "x86_64" -> "amd64"
            else -> Build.SUPPORTED_ABIS.firstOrNull().orEmpty()
        }
}
