package io.github.iffix.neutrino

import android.app.Activity
import android.app.Application
import android.content.Context
import android.content.Intent
import android.net.ConnectivityManager
import android.net.Network
import android.os.Build
import android.os.Bundle
import android.provider.DocumentsContract
import android.provider.Settings
import android.util.Log
import androidx.core.content.ContextCompat
import io.github.iffix.neutrino.binding.BindingStore
import io.github.iffix.neutrino.binding.KeystoreSecretSealer
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.ClientMachine
import io.github.iffix.neutrino.channel.HubConnections
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.channel.OkHttpHubTransport
import io.github.iffix.neutrino.files.ShareLoginStore
import io.github.iffix.neutrino.files.ShareRoot
import io.github.iffix.neutrino.files.SmbShareClient
import io.github.iffix.neutrino.forward.PortForwards
import io.github.iffix.neutrino.overlay.OverlayController
import io.github.iffix.neutrino.overlay.OverlayProbe
import io.github.iffix.neutrino.overlay.ServiceOverlayLauncher
import io.github.iffix.neutrino.remotedesktop.MissingRemoteDesktopCore
import io.github.iffix.neutrino.remotedesktop.RemoteDesktopCore
import io.github.iffix.neutrino.remotedesktop.RemoteDesktopSessions
import io.github.iffix.neutrino.remotedesktop.RustDeskNative
import io.github.iffix.neutrino.remotedesktop.RustDeskRemoteDesktopCore
import io.github.iffix.neutrino.settings.ClientSettingsStore
import io.github.iffix.neutrino.terminal.StreamOpener
import io.github.iffix.neutrino.terminal.TerminalTabs
import java.io.File
import java.net.Inet4Address
import java.net.InetAddress
import java.net.UnknownHostException
import java.util.Locale
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.transformLatest
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull

/** The app's process: what outlives one screen, made once. */
class NeutrinoApplication : Application() {
    /** Where every session and every service runs. */
    val scope: CoroutineScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    /** The language and the theme. */
    val settingsStore: ClientSettingsStore by lazy {
        ClientSettingsStore(
            preferences = getSharedPreferences(CLIENT_SETTINGS_FILE_NAME, Context.MODE_PRIVATE),
            phoneLanguage = Locale.getDefault().toLanguageTag(),
        )
    }

    /** Every hub joined, sealed under the Keystore's key. */
    val bindingStore: BindingStore by lazy {
        BindingStore(File(noBackupFilesDir, CLIENT_BINDINGS_FILE_NAME), KeystoreSecretSealer(CLIENT_KEYSTORE_ALIAS))
    }

    /** What this phone says about itself to every hub. */
    val machine: ClientMachine by lazy {
        ClientMachine(
            machineId = bindingStore.machineId,
            hostname = deviceName,
            arch = architecture,
            osVersion = Build.VERSION.RELEASE,
            version = BuildConfig.VERSION_NAME,
        )
    }

    /** One session per hub joined. */
    val connections: HubConnections by lazy {
        HubConnections(bindingStore, OkHttpHubTransport(), machine, ::resolveHubName, scope) { bindingId ->
            overlays.forget(bindingId)
            remoteDesktops.forget(bindingId)
            portForwards.forget(bindingId)
        }
    }

    /** Each hub's virtual network, and the one network the VPN runs. */
    val overlays: OverlayController by lazy {
        OverlayController(
            store = bindingStore,
            launcher = ServiceOverlayLauncher(this),
            scope = scope,
            probe = OverlayProbe::isReachable,
        ) { bindingId, url, isOnly -> connections.session(bindingId)?.preferAddress(url, isOnly) }
    }

    /** The one state document every screen draws: each hub with its virtual network and its jobs. */
    val hubs: StateFlow<List<HubView>> by lazy {
        combine(connections.views, overlays.lines) { views, lines ->
            views.map { view ->
                val line = lines[view.binding.id] ?: view.overlay
                view.copy(overlay = line, jobs = view.jobs.copy(overlayJob = line.job))
            }
        }.stateIn(scope, SharingStarted.Eagerly, emptyList())
    }

    /** The remote desktop Connects and the one viewer open. */
    val remoteDesktops: RemoteDesktopSessions by lazy {
        RemoteDesktopSessions(
            material = { bindingId, entryId ->
                connections.session(bindingId)?.openService(entryId) ?: ChannelResult.refused("unknown_hub")
            },
            scope = scope,
        )
    }

    /** The loopback forwards of the port entries and the local-only web entries. */
    val portForwards: PortForwards by lazy {
        PortForwards(
            material = { bindingId, entryId ->
                connections.session(bindingId)?.openService(entryId) ?: ChannelResult.refused("unknown_hub")
            },
            scope = scope,
        )
    }

    /** Every share the connected hubs publish, as roots of the system's Files, held a minute past a drop. */
    @OptIn(ExperimentalCoroutinesApi::class)
    val shareRoots: StateFlow<List<ShareRoot>> by lazy {
        connections.views.transformLatest { hubs ->
            while (true) {
                val now = System.currentTimeMillis()
                emit(ShareRoot.all(hubs, now))
                val end = ShareRoot.holdEndsAt(hubs, now) ?: break
                delay(end - now)
            }
        }.stateIn(scope, SharingStarted.Eagerly, emptyList())
    }

    /** The shares' logins. */
    val shareLogins: ShareLoginStore by lazy {
        ShareLoginStore(
            File(noBackupFilesDir, CLIENT_SHARE_LOGINS_FILE_NAME),
            KeystoreSecretSealer(CLIENT_KEYSTORE_ALIAS),
        )
    }

    /** The SMB connections the shares are read through. */
    val shares: SmbShareClient by lazy {
        SmbShareClient(
            CLIENT_SHARE_CONNECT_TIMEOUT_S,
            CLIENT_SHARE_IO_TIMEOUT_S,
            CLIENT_SHARE_IDLE_PROBE_S,
            CLIENT_SHARE_PROBE_TIMEOUT_S,
        )
    }

    /** Every terminal tab. */
    val terminalTabs: TerminalTabs by lazy {
        TerminalTabs(
            opener = { bindingId ->
                connections.session(bindingId)?.takeIf { it.view.value.isConnected }?.let { session ->
                    StreamOpener { kind, args, hasBytes -> session.openStream(kind, args, hasBytes) }
                }
            },
            scope = scope,
        )
    }

    /** What the remote desktop viewer decodes and sends input with. */
    val remoteDesktopCore: RemoteDesktopCore by lazy {
        if (RustDeskNative.isLoaded) RustDeskRemoteDesktopCore(filesDir.path) else MissingRemoteDesktopCore()
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

    override fun onCreate() {
        super.onCreate()
        connections.start()
        overlays.start(connections.views)
        terminalTabs.follow(connections.views)
        portForwards.follow(connections.views)
        scope.launch { ClientCoreHold.changes(bindingStore.bindings).collect { if (it) holdCore() } }
        scope.launch {
            shareRoots.collect {
                contentResolver.notifyChange(DocumentsContract.buildRootsUri(CLIENT_FILES_AUTHORITY), null)
            }
        }
        registerActivityLifecycleCallbacks(ForegroundWatch())
        val connectivity = getSystemService(ConnectivityManager::class.java)
        connectivity.registerDefaultNetworkCallback(NetworkWatch())
    }

    private fun holdCore() {
        try {
            ContextCompat.startForegroundService(this, Intent(this, ClientCoreService::class.java))
        } catch (error: IllegalStateException) {
            Log.w(CLIENT_LOG_TAG, "the app core's service could not start: ${error.message}")
        }
    }

    private suspend fun resolveHubName(): String? = withContext(Dispatchers.IO) {
        withTimeoutOrNull(CLIENT_CONNECT_TIMEOUT_S * 1000) {
            try {
                InetAddress.getAllByName(CLIENT_HUB_NAME).firstOrNull { it is Inet4Address }?.hostAddress
            } catch (_: UnknownHostException) {
                null
            }
        }
    }

    private inner class ForegroundWatch : ActivityLifecycleCallbacks {
        private var started = 0

        override fun onActivityStarted(activity: Activity) {
            started += 1
            if (started != 1) return
            shares.markStale()
            connections.resume()
            if (bindingStore.bindings.value.isNotEmpty()) holdCore()
        }

        override fun onActivityStopped(activity: Activity) {
            started -= 1
        }

        override fun onActivityCreated(activity: Activity, savedInstanceState: Bundle?) = Unit

        override fun onActivityResumed(activity: Activity) = Unit

        override fun onActivityPaused(activity: Activity) = Unit

        override fun onActivitySaveInstanceState(activity: Activity, outState: Bundle) = Unit

        override fun onActivityDestroyed(activity: Activity) = Unit
    }

    private inner class NetworkWatch : ConnectivityManager.NetworkCallback() {
        private var current: Network? = null

        override fun onAvailable(network: Network) {
            val previous = current
            current = network
            if (previous != null && previous != network) connections.networkChanged()
        }

        override fun onLost(network: Network) {
            if (network == current) current = null
        }
    }
}
