package io.github.iffix.neutrino

import android.app.Application
import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.os.Build
import android.os.SystemClock
import android.provider.DocumentsContract
import android.provider.Settings
import io.github.iffix.neutrino.binding.BindingStore
import io.github.iffix.neutrino.binding.KeystoreSecretSealer
import io.github.iffix.neutrino.channel.ClientMachine
import io.github.iffix.neutrino.channel.HubConnections
import io.github.iffix.neutrino.channel.OkHttpHubTransport
import io.github.iffix.neutrino.files.ShareLoginStore
import io.github.iffix.neutrino.files.ShareRoot
import io.github.iffix.neutrino.files.SmbShareClient
import io.github.iffix.neutrino.overlay.OverlayController
import io.github.iffix.neutrino.overlay.ServiceOverlayLauncher
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
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
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
        HubConnections(bindingStore, OkHttpHubTransport(), machine, ::resolveHubName, scope)
    }

    /** The wish to be on a hub's virtual network, and the one network the VPN runs. */
    val overlays: OverlayController by lazy {
        OverlayController(bindingStore, ServiceOverlayLauncher(this), SystemClock::elapsedRealtime) { bindingId ->
            connections.session(bindingId)?.networkChanged()
        }
    }

    /** Every share the connected hubs publish, as roots of the system's Files. */
    val shareRoots: StateFlow<List<ShareRoot>> by lazy {
        connections.views.map { ShareRoot.all(it) }.stateIn(scope, SharingStarted.Eagerly, emptyList())
    }

    /** The shares' logins. */
    val shareLogins: ShareLoginStore by lazy {
        ShareLoginStore(
            File(noBackupFilesDir, CLIENT_SHARE_LOGINS_FILE_NAME),
            KeystoreSecretSealer(CLIENT_KEYSTORE_ALIAS),
        )
    }

    /** The SMB connections the shares are read through. */
    val shares: SmbShareClient by lazy { SmbShareClient(CLIENT_SHARE_TIMEOUT_S) }

    /** Every terminal tab. */
    val terminalTabs: TerminalTabs by lazy {
        TerminalTabs(
            preferences = getSharedPreferences(CLIENT_TERMINAL_FILE_NAME, Context.MODE_PRIVATE),
            opener = { bindingId ->
                connections.session(bindingId)?.takeIf { it.view.value.isConnected }?.let { session ->
                    StreamOpener { kind, args, hasBytes -> session.openStream(kind, args, hasBytes) }
                }
            },
            scope = scope,
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

    override fun onCreate() {
        super.onCreate()
        connections.start()
        overlays.start(scope, connections.views)
        scope.launch {
            shareRoots.collect {
                contentResolver.notifyChange(DocumentsContract.buildRootsUri(CLIENT_FILES_AUTHORITY), null)
            }
        }
        val connectivity = getSystemService(ConnectivityManager::class.java)
        connectivity.registerDefaultNetworkCallback(NetworkWatch())
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
