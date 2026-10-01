package io.github.iffix.neutrino.overlay

import android.os.Build
import io.github.iffix.neutrino.OVERLAY_NETBIRD_DEFAULT_MANAGEMENT_URL
import io.github.iffix.neutrino.channel.ChannelOverlay
import io.github.iffix.neutrino.channel.ChannelResult
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
 * its kept configuration until stopped.
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
    ) {
        thread(name = "netbird") { run(overlay, tun, report) }
    }

    override fun stop() {
        isStopped = true
        client?.stop()
    }

    private fun run(
        overlay: ChannelOverlay,
        tun: TunBuilder,
        report: (OverlayPhase, String, ChannelResult.Refused?) -> Unit,
    ) {
        report(OverlayPhase.JOINING, "", null)
        dir.mkdirs()
        val config = File(dir, "config.json")
        val registered = File(dir, "setup_key.sha256")
        val keyDigest = MessageDigest.getInstance("SHA-256").digest(overlay.setupKey.toByteArray())
            .joinToString("") { "%02x".format(it) }
        try {
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
            val address = StringBuilder()
            val running = Android.newClient(
                Build.VERSION.SDK_INT.toLong(),
                deviceName,
                version,
                Tun(tun),
                Interfaces(),
                Changes(),
            )
            running.setConnectionListener(Listener(address, report))
            client = running
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

    private class Tun(private val tun: TunBuilder) : TunAdapter {
        override fun configureInterface(
            address: String,
            addressV6: String?,
            mtu: Long,
            dns: String?,
            searchDomains: String?,
            routes: String?,
        ): Long {
            val (ip, prefix) = address.split('/').let { it[0] to (it.getOrNull(1)?.toInt() ?: 32) }
            val fd = tun.establish(
                address = ip,
                prefix = prefix,
                mtu = mtu.toInt(),
                routes = routes.orEmpty().split(';').filter { it.isNotBlank() },
                dnsServers = listOfNotNull(dns?.takeIf { it.isNotBlank() }),
                searchDomains = searchDomains.orEmpty().split(';').filter { it.isNotBlank() },
                isHandedOver = true,
            ) ?: throw IllegalStateException("the phone refused the VPN interface")
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

    private class Changes : NetworkChangeListener {
        override fun onNetworkChanged(routes: String?) = Unit

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
    ) : ConnectionListener {
        override fun onAddressChanged(fqdn: String?, ip: String?) {
            address.setLength(0)
            address.append(ip.orEmpty().substringBefore('/'))
        }

        override fun onConnected() = report(OverlayPhase.ON, address.toString(), null)

        override fun onConnecting() = report(OverlayPhase.JOINING, "", null)

        override fun onDisconnected() = report(OverlayPhase.JOINING, "", null)

        override fun onDisconnecting() = report(OverlayPhase.LEAVING, "", null)

        override fun onPeersListChanged(count: Long) = Unit

        override fun onStateChanged(state: Long) = Unit
    }
}
