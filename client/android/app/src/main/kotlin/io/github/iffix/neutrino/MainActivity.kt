package io.github.iffix.neutrino

import android.os.Build
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
        val platform = "$CLIENT_PLATFORM_OS/${application.architecture} · Android ${Build.VERSION.RELEASE}"
        val hubs by application.hubs.collectAsStateWithLifecycle()
        val notices by application.connections.notices.collectAsStateWithLifecycle()
        val join by application.connections.join.collectAsStateWithLifecycle()
        val context = LocalContext.current
        val actions =
            remember(context) {
                ClientController(
                    context,
                    application.connections,
                    application.overlays,
                    application.remoteDesktops,
                    application.shares,
                    application.shareLogins,
                    application.portForwards,
                )
            }
        NeutrinoTheme(palette, words) {
            AppShell(
                deviceName = application.deviceName,
                platform = platform,
                version = BuildConfig.VERSION_NAME,
                settings = settings,
                onSaveSettings = application.settingsStore::save,
                hubs = hubs,
                notices = notices,
                join = join,
                actions = actions,
                terminalTabs = application.terminalTabs,
                desktops = application.remoteDesktops,
                forwards = application.portForwards,
                remoteDesktopCore = application.remoteDesktopCore,
            )
        }
    }
}
