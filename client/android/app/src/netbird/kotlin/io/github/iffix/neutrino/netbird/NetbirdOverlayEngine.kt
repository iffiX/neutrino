package io.github.iffix.neutrino.netbird

import android.os.Build
import android.util.Log
import io.github.iffix.neutrino.CLIENT_LOG_TAG
import io.github.iffix.neutrino.channel.ChannelOverlay
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.overlay.OverlayEngine
import io.github.iffix.neutrino.overlay.OverlayPhase
import io.github.iffix.neutrino.overlay.TunBuilder
import io.netbird.gomobile.android.Android
import io.netbird.gomobile.android.ConnectionListener
import io.netbird.gomobile.android.DNSList
import io.netbird.gomobile.android.DnsReadyListener
import io.netbird.gomobile.android.ErrListener
import io.netbird.gomobile.android.IFaceDiscover
import io.netbird.gomobile.android.NetworkChangeListener
import io.netbird.gomobile.android.PlatformFiles
import io.netbird.gomobile.android.TunAdapter
import java.io.File
import java.net.NetworkInterface
import java.security.MessageDigest
import java.util.concurrent.CompletableFuture
import kotlin.concurrent.thread

/**
 * NetBird's client in the app: the peer registers once with the hub's setup key, then runs from
 * its kept configuration until stopped. When the core says its routes or search domains changed,
 * the TUN device is built again with the core's whole new set and handed back to the core. The
 * core's peers-changed callback is the engine's peer list change.
 *
 * @param dir Where this hub's NetBird configuration and state live.
 * @param deviceName The name the peer registers under.
 * @param version The app's version, which NetBird's management sees.
 */
class NetbirdOverlayEngine(private val dir: File, private val deviceName: String, private val version: String) :
    OverlayEngine {
    @Volatile
    private var client: io.netbird.gomobile.android.Client? = null

    @Volatile
    private var isStopped = false

    override fun start(
        overlay: ChannelOverlay,
        tun: TunBuilder,
        report: (OverlayPhase, String, ChannelResult.Refused?) -> Unit,
        onPeersChanged: () -> Unit,
    ) {
        thread(name = "netbird") { run(overlay, tun, report, onPeersChanged) }
    }

    override fun stop() {
        isStopped = true
        client?.stop()
    }

    private fun run(
        overlay: ChannelOverlay,
        tun: TunBuilder,
        report: (OverlayPhase, String, ChannelResult.Refused?) -> Unit,
        onPeersChanged: () -> Unit,
    ) {
        report(OverlayPhase.JOINING, "", null)
        dir.mkdirs()
        val config = File(dir, "config.json")
        val registered = File(dir, "setup_key.sha256")
        val keyDigest = MessageDigest.getInstance("SHA-256").digest(overlay.setupKey.toByteArray())
            .joinToString("") { "%02x".format(it) }
        try {
            val address = StringBuilder()
            val adapter = Tun(tun)
            val running = Android.newClient(
                Build.VERSION.SDK_INT.toLong(),
                deviceName,
                version,
                adapter,
                Interfaces(),
                Changes { thread(name = "netbird-routes") { renew(adapter, tun) } },
            )
            running.setConnectionListener(Listener(address, report, onPeersChanged))
            client = running
            if (!config.exists() || !registered.exists() || registered.readText() != keyDigest) {
                val management = overlay.managementUrl.ifEmpty { OVERLAY_NETBIRD_DEFAULT_MANAGEMENT_URL }
                val done = CompletableFuture<Exception?>()
                Android.newAuth(config.path, management).loginWithSetupKeyAndSaveConfig(
                    object : ErrListener {
                        override fun onSuccess() {
                            done.complete(null)
                        }

                        override fun onError(error: Exception?) {
                            done.complete(error ?: IllegalStateException("login failed"))
                        }
                    },
                    overlay.setupKey,
                    deviceName,
                )
                done.get()?.let { throw it }
                registered.writeText(keyDigest)
            }
            if (isStopped) return
            running.runWithoutLogin(Files(dir, config), DNSList(), Ready(), Android.newEnvList())
            report(OverlayPhase.OFF, "", null)
        } catch (error: Exception) {
            report(
                OverlayPhase.FAILED,
                "",
                ChannelResult.refused(
                    "overlay_join_failed",
                    "detail" to (error.message ?: ""),
                ),
            )
        } finally {
            client = null
        }
    }

    private fun renew(adapter: Tun, tun: TunBuilder) = synchronized(adapter) {
        val running = client ?: return@synchronized
        val shape = adapter.shape ?: return@synchronized
        val settings = try {
            running.tunSettings
        } catch (error: Exception) {
            Log.w(CLIENT_LOG_TAG, "NetBird's routes could not be read: ${error.message}")
            return@synchronized
        }
        val routes = NetbirdRoutes.parse(settings.routes)
        val searchDomains = NetbirdRoutes.parse(settings.searchDomains)
        if (routes == shape.routes && searchDomains == shape.searchDomains) return@synchronized
        Log.i(CLIENT_LOG_TAG, "NetBird's routes changed from ${shape.routes} to $routes")
        val fd = tun.establish(shape.address, shape.prefix, shape.mtu, routes, shape.dnsServers, searchDomains, true)
        if (fd == null) {
            Log.w(CLIENT_LOG_TAG, "the phone refused the rebuilt VPN interface")
            return@synchronized
        }
        try {
            running.renewTun(fd.toLong())
            adapter.shape = shape.copy(routes = routes, searchDomains = searchDomains)
        } catch (error: Exception) {
            Log.w(CLIENT_LOG_TAG, "NetBird did not take the rebuilt VPN interface: ${error.message}")
        }
    }

    private data class TunShape(
        val address: String,
        val prefix: Int,
        val mtu: Int,
        val routes: List<String>,
        val dnsServers: List<String>,
        val searchDomains: List<String>,
    )

    private class Tun(private val tun: TunBuilder) : TunAdapter {
        @Volatile
        var shape: TunShape? = null

        override fun configureInterface(
            address: String,
            addressV6: String?,
            mtu: Long,
            dns: String?,
            searchDomains: String?,
            routes: String?,
        ): Long {
            val (ip, prefix) = address.split('/').let { it[0] to (it.getOrNull(1)?.toInt() ?: 32) }
            val wanted = TunShape(
                address = ip,
                prefix = prefix,
                mtu = mtu.toInt(),
                routes = NetbirdRoutes.parse(routes),
                dnsServers = listOfNotNull(dns?.takeIf { it.isNotBlank() }),
                searchDomains = NetbirdRoutes.parse(searchDomains),
            )
            val fd = tun.establish(
                address = wanted.address,
                prefix = wanted.prefix,
                mtu = wanted.mtu,
                routes = wanted.routes,
                dnsServers = wanted.dnsServers,
                searchDomains = wanted.searchDomains,
                isHandedOver = true,
            ) ?: throw IllegalStateException("the phone refused the VPN interface")
            shape = wanted
            Log.i(CLIENT_LOG_TAG, "NetBird's VPN interface carries ${wanted.routes}")
            return fd.toLong()
        }

        override fun protectSocket(fd: Int): Boolean = tun.protect(fd)

        override fun updateAddr(address: String?) = Unit
    }

    private class Interfaces : IFaceDiscover {
        override fun iFaces(): String = NetworkInterface.getNetworkInterfaces().toList().joinToString("\n") { face ->
            val flags =
                listOf(
                    face.isUp,
                    !face.isLoopback && !face.isPointToPoint,
                    face.isLoopback,
                    face.isPointToPoint,
                    face.supportsMulticast(),
                )
            val head = "${face.name} ${face.index} ${face.mtu} " + flags.joinToString(" ")
            head + "|" +
                face.interfaceAddresses.joinToString(" ") { "${it.address.hostAddress}/${it.networkPrefixLength}" }
        }
    }

    private class Changes(private val onChanged: () -> Unit) : NetworkChangeListener {
        override fun onNetworkChanged(routes: String?) = onChanged()

        override fun setInterfaceIP(address: String?) = Unit

        override fun setInterfaceIPv6(address: String?) = Unit
    }

    private class Ready : DnsReadyListener {
        override fun onReady() = Unit
    }

    private class Files(private val dir: File, private val config: File) : PlatformFiles {
        override fun cacheDir(): String = File(dir, "cache").apply { mkdirs() }.path

        override fun configurationFilePath(): String = config.path

        override fun stateFilePath(): String = File(dir, "state.json").path
    }

    private class Listener(
        private val address: StringBuilder,
        private val report: (OverlayPhase, String, ChannelResult.Refused?) -> Unit,
        private val onPeersChanged: () -> Unit,
    ) : ConnectionListener {
        override fun onAddressChanged(fqdn: String?, ip: String?) {
            address.setLength(0)
            address.append(ip.orEmpty())
        }

        override fun onConnected() = report(OverlayPhase.ON, address.toString(), null)

        override fun onConnecting() = report(OverlayPhase.JOINING, "", null)

        override fun onDisconnected() = report(OverlayPhase.JOINING, "", null)

        override fun onDisconnecting() = report(OverlayPhase.LEAVING, "", null)

        override fun onPeersListChanged(count: Long) = onPeersChanged()

        override fun onStateChanged(state: Long) = Unit
    }
}
