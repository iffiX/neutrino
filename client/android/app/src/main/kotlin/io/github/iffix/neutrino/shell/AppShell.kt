package io.github.iffix.neutrino.shell

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import io.github.iffix.neutrino.CLIENT_SIDEBAR_MIN_WIDTH_DP
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.screen.AboutScreen
import io.github.iffix.neutrino.screen.AiScreen
import io.github.iffix.neutrino.screen.FilesScreen
import io.github.iffix.neutrino.screen.HubsScreen
import io.github.iffix.neutrino.screen.JoinScreen
import io.github.iffix.neutrino.screen.PortsScreen
import io.github.iffix.neutrino.screen.RemoteDesktopScreen
import io.github.iffix.neutrino.screen.SettingsScreen
import io.github.iffix.neutrino.screen.TerminalScreen
import io.github.iffix.neutrino.screen.WebScreen
import io.github.iffix.neutrino.settings.ClientSettings

/**
 * Every screen under one frame: the bottom bar in portrait, the sidebar in a wide landscape
 * window, the top bar over the open screen either way.
 *
 * @param identity This phone's name, platform and version, for the sidebar's foot.
 * @param version The app's version.
 * @param settings The settings in force.
 * @param onSaveSettings What saving the settings does.
 */
@Composable
fun AppShell(identity: String, version: String, settings: ClientSettings, onSaveSettings: (ClientSettings) -> Unit) {
    val palette = NeutrinoTheme.palette
    val words = NeutrinoTheme.words
    val navigation = rememberNavController()
    val entry by navigation.currentBackStackEntryAsState()
    val screen = AppScreen.of(entry?.destination?.route)
    val tab = screen.parent ?: screen
    val open = { target: AppScreen -> openTab(navigation, target) }
    val back: (() -> Unit)? = if (screen.parent != null) ({ navigation.popBackStack() }) else null
    BoxWithConstraints(modifier = Modifier.fillMaxSize().background(palette.bg)) {
        val isWide = maxWidth > maxHeight && maxWidth >= CLIENT_SIDEBAR_MIN_WIDTH_DP.dp
        Row(modifier = Modifier.fillMaxSize().statusBarsPadding()) {
            if (isWide) SideBar(current = tab, onOpen = open, identity = identity)
            Column(modifier = Modifier.weight(1f)) {
                TopBar(
                    title = words.word(screen.titleKey),
                    overlayValue = words.word("ui.overlay_off"),
                    onBack = back,
                    isWide = isWide,
                )
                NavHost(
                    navController = navigation,
                    startDestination = AppScreen.HUBS.route,
                    modifier = Modifier.weight(1f),
                ) {
                    val join = { navigation.navigate(AppScreen.JOIN.route) }
                    composable(AppScreen.HUBS.route) { HubsScreen(onJoin = join) }
                    composable(AppScreen.WEB.route) { WebScreen(onJoin = join) }
                    composable(AppScreen.PORTS.route) { PortsScreen(onJoin = join) }
                    composable(AppScreen.AI.route) { AiScreen(onJoin = join) }
                    composable(AppScreen.FILES.route) { FilesScreen(onJoin = join) }
                    composable(AppScreen.TERMINALS.route) { TerminalScreen(onJoin = join) }
                    composable(AppScreen.REMOTE_DESKTOP.route) { RemoteDesktopScreen(onJoin = join) }
                    composable(AppScreen.SETTINGS.route) {
                        SettingsScreen(
                            saved = settings,
                            onSave = onSaveSettings,
                            onAbout = { navigation.navigate(AppScreen.ABOUT.route) },
                        )
                    }
                    composable(AppScreen.JOIN.route) { JoinScreen() }
                    composable(AppScreen.ABOUT.route) { AboutScreen(version) }
                }
                if (!isWide) BottomBar(current = tab, onOpen = open)
            }
        }
    }
}

private fun openTab(navigation: NavHostController, target: AppScreen) {
    navigation.navigate(target.route) {
        popUpTo(navigation.graph.findStartDestination().id) { saveState = true }
        launchSingleTop = true
        restoreState = true
    }
}
