package io.github.iffix.neutrino

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.iffix.neutrino.design.NeutrinoPalette
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.shell.AppShell
import io.github.iffix.neutrino.shell.ClientController
import io.github.iffix.neutrino.words.WordCatalog

/** The one window: every screen is drawn inside it. */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val application = application as NeutrinoApplication
        setContent { NeutrinoRoot(application) }
    }

    @Composable
    private fun NeutrinoRoot(application: NeutrinoApplication) {
        val settings by application.settingsStore.settings.collectAsStateWithLifecycle()
        val isDark = when (settings.theme) {
            "dark" -> true
            "light" -> false
            else -> isSystemInDarkTheme()
        }
        val palette = if (isDark) NeutrinoPalette.dark else NeutrinoPalette.light
        val assets = LocalContext.current.assets
        val words = remember(settings.language) { WordCatalog.load(assets, settings.language) }
        LaunchedEffect(isDark) {
            val bar = palette.bg.toArgb()
            val style = if (isDark) SystemBarStyle.dark(bar) else SystemBarStyle.light(bar, bar)
            enableEdgeToEdge(statusBarStyle = style, navigationBarStyle = style)
        }
        val identity =
            "${application.deviceName} · android/${application.architecture} · client ${BuildConfig.VERSION_NAME}"
        val hubs by application.connections.views.collectAsStateWithLifecycle(emptyList())
        val context = LocalContext.current
        val actions =
            remember(context) {
                ClientController(
                    context,
                    application.connections,
                    application.overlays,
                    application.shares,
                    application.shareLogins,
                )
            }
        val overlayStatus by application.overlays.status.collectAsStateWithLifecycle()
        NeutrinoTheme(palette, words) {
            AppShell(
                identity = identity,
                version = BuildConfig.VERSION_NAME,
                settings = settings,
                onSaveSettings = application.settingsStore::save,
                hubs = hubs,
                actions = actions,
                overlayStatus = overlayStatus,
                terminalTabs = application.terminalTabs,
                remoteDesktopCore = application.remoteDesktopCore,
            )
        }
    }
}
