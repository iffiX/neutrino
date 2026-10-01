package io.github.iffix.neutrino.shell

import android.app.Activity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.EnterTransition
import androidx.compose.animation.ExitTransition
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import io.github.iffix.neutrino.CLIENT_BOTTOM_BAR_HEIGHT_DP
import io.github.iffix.neutrino.CLIENT_SIDEBAR_MIN_WIDTH_DP
import io.github.iffix.neutrino.channel.HubJoin
import io.github.iffix.neutrino.channel.HubNotice
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.design.ArmState
import io.github.iffix.neutrino.design.LocalArm
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.design.disarmOnPress
import io.github.iffix.neutrino.remotedesktop.RemoteDesktopCore
import io.github.iffix.neutrino.remotedesktop.RemoteDesktopSessions
import io.github.iffix.neutrino.remotedesktop.RemoteDesktopViewer
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
import io.github.iffix.neutrino.terminal.TerminalTabs

/**
 * Every screen under one frame: the bottom bar in portrait, the sidebar in a window wider than
 * tall and at least 720 dp wide, the top bar over the open screen either way. Pages change with
 * no transition.
 *
 * @param identity This phone's name, platform and version, for the sidebar's foot.
 * @param version The app's version.
 * @param settings The settings in force.
 * @param onSaveSettings What saving the settings does.
 * @param hubs Every hub joined, with its virtual network and its jobs.
 * @param notices The hubs that no longer know this phone, for a minute.
 * @param join The join the app core runs.
 * @param actions What the screens can do.
 * @param terminalTabs Every terminal tab.
 * @param desktops The remote desktop Connects and the viewer open.
 * @param remoteDesktopCore What the remote desktop viewer draws and sends input with.
 */
@Composable
fun AppShell(
    identity: String,
    version: String,
    settings: ClientSettings,
    onSaveSettings: (ClientSettings) -> Unit,
    hubs: List<HubView>,
    notices: List<HubNotice>,
    join: HubJoin,
    actions: ClientActions,
    terminalTabs: TerminalTabs,
    desktops: RemoteDesktopSessions,
    remoteDesktopCore: RemoteDesktopCore,
) {
    var consentFor by remember { mutableStateOf("") }
    val consent = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode == Activity.RESULT_OK && consentFor.isNotEmpty()) actions.connectOverlay(consentFor)
        consentFor = ""
    }
    val connectOverlay = { bindingId: String ->
        val ask = actions.overlayConsent()
        if (ask == null) {
            actions.connectOverlay(bindingId)
        } else {
            consentFor = bindingId
            consent.launch(ask)
        }
    }
    val connecting by desktops.connecting.collectAsStateWithLifecycle()
    val desktopErrors by desktops.errors.collectAsStateWithLifecycle()
    val viewing by desktops.viewing.collectAsStateWithLifecycle()
    val arm = remember { ArmState() }
    val palette = NeutrinoTheme.palette
    val words = NeutrinoTheme.words
    val navigation = rememberNavController()
    val entry by navigation.currentBackStackEntryAsState()
    val screen = AppScreen.of(entry?.destination?.route)
    val tab = screen.parent ?: screen
    val open = { target: AppScreen -> openTab(navigation, target) }
    val back: (() -> Unit)? = if (screen.parent != null) ({ navigation.popBackStack() }) else null
    CompositionLocalProvider(LocalArm provides arm) {
        BoxWithConstraints(modifier = Modifier.fillMaxSize().background(palette.bg).disarmOnPress(arm)) {
            val isWide = maxWidth > maxHeight && maxWidth >= CLIENT_SIDEBAR_MIN_WIDTH_DP.dp
            Row(modifier = Modifier.fillMaxSize().statusBarsPadding()) {
                if (isWide) SideBar(current = tab, onOpen = open, identity = identity)
                Column(modifier = Modifier.weight(1f)) {
                    TopBar(
                        title = words.word(screen.titleKey),
                        isRefreshing = hubs.any { it.jobs.isRefreshing },
                        onRefresh = actions::refresh,
                        onBack = back,
                        isWide = isWide,
                    )
                    val below = if (isWide) {
                        Modifier
                    } else {
                        Modifier
                            .consumeWindowInsets(WindowInsets.navigationBars)
                            .consumeWindowInsets(PaddingValues(bottom = CLIENT_BOTTOM_BAR_HEIGHT_DP.dp))
                    }
                    NavHost(
                        navController = navigation,
                        startDestination = AppScreen.HUBS.route,
                        modifier = Modifier.weight(1f).then(below),
                        enterTransition = { EnterTransition.None },
                        exitTransition = { ExitTransition.None },
                        popEnterTransition = { EnterTransition.None },
                        popExitTransition = { ExitTransition.None },
                    ) {
                        val toJoin = {
                            actions.clearJoin()
                            navigation.navigate(AppScreen.JOIN.route)
                        }
                        composable(AppScreen.HUBS.route) {
                            HubsScreen(
                                hubs,
                                notices,
                                onJoin = toJoin,
                                onLeave = actions::leave,
                                onReconnect = actions::reconnect,
                                onOverlayConnect = connectOverlay,
                                onOverlayCancel = actions::cancelOverlay,
                                onOverlayDisconnect = actions::disconnectOverlay,
                                onOverlayPick = actions::pickOverlay,
                            )
                        }
                        composable(AppScreen.WEB.route) { WebScreen(hubs, onOpen = actions::openUrl) }
                        composable(AppScreen.PORTS.route) { PortsScreen(hubs, onCopy = { actions.copy(it) }) }
                        composable(AppScreen.AI.route) {
                            AiScreen(hubs, material = actions::serviceMaterial, onCopy = actions::copy)
                        }
                        composable(AppScreen.FILES.route) {
                            FilesScreen(
                                hubs,
                                hasLogin = actions::hasShareLogin,
                                onLogin = actions::giveShareLogin,
                                onForget = actions::forgetShareLogin,
                                onOpen = actions::openShare,
                            )
                        }
                        composable(AppScreen.TERMINALS.route) { TerminalScreen(hubs, terminalTabs) }
                        composable(AppScreen.REMOTE_DESKTOP.route) {
                            RemoteDesktopScreen(
                                hubs,
                                connecting = connecting,
                                errors = desktopErrors,
                                viewingKey = viewing?.first,
                                onConnect = actions::connectDesktop,
                            )
                        }
                        composable(AppScreen.SETTINGS.route) {
                            SettingsScreen(saved = settings, version = version, onSave = onSaveSettings)
                        }
                        composable(AppScreen.JOIN.route) {
                            JoinScreen(
                                join = join,
                                onJoin = actions::join,
                                onJoined = {
                                    actions.clearJoin()
                                    navigation.popBackStack()
                                },
                            )
                        }
                    }
                    if (!isWide) BottomBar(current = tab, onOpen = open)
                }
            }
            viewing?.let { (_, target) ->
                RemoteDesktopViewer(target, remoteDesktopCore, onCopied = {
                    actions.copy(it)
                }, onClose = actions::closeDesktop)
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
