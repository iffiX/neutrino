package io.github.iffix.neutrino.overlay

import android.content.Context
import android.content.Intent
import android.net.VpnService
import android.os.ParcelFileDescriptor
import android.util.Log
import io.github.iffix.neutrino.BuildConfig
import io.github.iffix.neutrino.CLIENT_LOG_TAG
import io.github.iffix.neutrino.Edition
import io.github.iffix.neutrino.NeutrinoApplication
import io.github.iffix.neutrino.OVERLAY_PROVIDER_EASYTIER
import io.github.iffix.neutrino.OVERLAY_SERVICE_ACTION_START
import io.github.iffix.neutrino.OVERLAY_SERVICE_ACTION_STOP
import io.github.iffix.neutrino.OVERLAY_SERVICE_EXTRA_BINDING
import io.github.iffix.neutrino.OVERLAY_SERVICE_EXTRA_PROVIDER
import io.github.iffix.neutrino.channel.ChannelResult
import java.io.File
import java.io.IOException
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

/**
 * The app's one VPN: hosts whichever engine the hub's material names, one network at a time.
 * The material is read from the binding store; an intent carries only the binding and the provider.
 * Every engine's start and stop runs in order on one worker thread, and each engine gets a TUN
 * builder of its own.
 */
class OverlayVpnService : VpnService() {
    @Volatile
    private var engine: OverlayEngine? = null
    private var tun: ServiceTunBuilder? = null
    private var running: Pair<String, String>? = null
    private var lastStartId = 0

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        lastStartId = startId
        when (intent?.action) {
            OVERLAY_SERVICE_ACTION_START -> {
                val bindingId = intent.getStringExtra(OVERLAY_SERVICE_EXTRA_BINDING).orEmpty()
                val provider = intent.getStringExtra(OVERLAY_SERVICE_EXTRA_PROVIDER).orEmpty()
                if (running != bindingId to provider) begin(bindingId, provider)
            }

            OVERLAY_SERVICE_ACTION_STOP -> {
                end()
                engineQueue.execute { stopSelf(startId) }
            }
        }
        return START_NOT_STICKY
    }

    override fun onRevoke() {
        end()
        (application as NeutrinoApplication).overlays.revoked()
        val startId = lastStartId
        engineQueue.execute { stopSelf(startId) }
    }

    override fun onDestroy() {
        end()
        super.onDestroy()
    }

    private fun begin(bindingId: String, provider: String) {
        end()
        val app = application as NeutrinoApplication
        val overlay = app.bindingStore.get(bindingId)?.overlays?.firstOrNull { it.provider == provider }
        val dir = File(noBackupFilesDir, "overlay/$provider/$bindingId")
        val created = if (provider == OVERLAY_PROVIDER_EASYTIER) {
            EasyTierOverlayEngine(dir, app.deviceName)
        } else {
            Edition.overlayPart(provider)?.engine(dir, app.deviceName, BuildConfig.VERSION_NAME)
        }
        if (overlay == null || created == null) {
            app.overlays.report(
                OverlayStatus(
                    bindingId,
                    provider,
                    OverlayPhase.FAILED,
                    refusal = ChannelResult.refused("overlay_missing"),
                ),
            )
            return
        }
        val builder = ServiceTunBuilder()
        engine = created
        tun = builder
        running = bindingId to provider
        engineQueue.execute {
            created.start(overlay, builder) { phase, address, refusal ->
                Log.i(
                    CLIENT_LOG_TAG,
                    "virtual network $provider: $phase $address ${refusal?.code.orEmpty()} ${refusal?.wordParams.orEmpty()}",
                )
                if (engine === created) {
                    app.overlays.report(OverlayStatus(bindingId, provider, phase, address, refusal))
                }
            }
        }
    }

    private fun end() {
        val stopping = running
        val stopped = engine
        val device = tun
        engine = null
        tun = null
        running = null
        engineQueue.execute {
            stopped?.stop()
            device?.close()
        }
        if (stopping != null) {
            (application as NeutrinoApplication).overlays.report(
                OverlayStatus(stopping.first, stopping.second, OverlayPhase.OFF),
            )
        }
    }

    private inner class ServiceTunBuilder : TunBuilder {
        private var held: ParcelFileDescriptor? = null
        private var isClosed = false

        override fun establish(
            address: String,
            prefix: Int,
            mtu: Int,
            routes: List<String>,
            dnsServers: List<String>,
            searchDomains: List<String>,
            isHandedOver: Boolean,
        ): Int? {
            val builder = Builder()
                .setSession("Neutrino")
                .setMtu(mtu)
                .addAddress(address, prefix)
            for (route in routes) {
                val (network, length) = route.split('/').let { it[0] to (it.getOrNull(1)?.toInt() ?: 32) }
                if (':' !in network) builder.addRoute(network, length)
            }
            dnsServers.forEach { builder.addDnsServer(it) }
            searchDomains.forEach { builder.addSearchDomain(it) }
            synchronized(this) {
                if (isClosed) return null
                val device = builder.establish() ?: return null
                if (isHandedOver) return device.detachFd()
                closeHeld()
                held = device
                return device.fd
            }
        }

        override fun protect(fd: Int): Boolean = this@OverlayVpnService.protect(fd)

        override fun close() = synchronized(this) {
            isClosed = true
            closeHeld()
        }

        private fun closeHeld() {
            try {
                held?.close()
            } catch (_: IOException) {
                // The engine closed the device already.
            }
            held = null
        }
    }

    companion object {
        private val engineQueue: ExecutorService = Executors.newSingleThreadExecutor { Thread(it, "overlay-engine") }

        /**
         * The intent that runs one hub's network.
         *
         * @param context Any context of the app.
         * @param bindingId The hub.
         * @param provider The network's provider.
         * @return The intent.
         */
        fun startIntent(context: Context, bindingId: String, provider: String): Intent =
            Intent(context, OverlayVpnService::class.java)
                .setAction(OVERLAY_SERVICE_ACTION_START)
                .putExtra(OVERLAY_SERVICE_EXTRA_BINDING, bindingId)
                .putExtra(OVERLAY_SERVICE_EXTRA_PROVIDER, provider)

        /**
         * The intent that leaves the network.
         *
         * @param context Any context of the app.
         * @return The intent.
         */
        fun stopIntent(context: Context): Intent =
            Intent(context, OverlayVpnService::class.java).setAction(OVERLAY_SERVICE_ACTION_STOP)
    }
}
