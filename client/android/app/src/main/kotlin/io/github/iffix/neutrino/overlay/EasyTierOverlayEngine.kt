package io.github.iffix.neutrino.overlay

import com.easytier.jni.EasyTierJNI
import io.github.iffix.neutrino.OVERLAY_EASYTIER_INSTANCE
import io.github.iffix.neutrino.OVERLAY_EASYTIER_MODE_CONSOLE
import io.github.iffix.neutrino.OVERLAY_POLL_MILLIS
import io.github.iffix.neutrino.OVERLAY_TUN_MTU
import io.github.iffix.neutrino.channel.ChannelOverlay
import io.github.iffix.neutrino.channel.ChannelResult
import java.io.File
import kotlin.concurrent.thread

/**
 * EasyTier's core in the app: a manual network run from its TOML, or a console's web client
 * that runs the networks the console pushes; the first network with an address gets the TUN
 * device, rebuilt when the address or the routed subnets change.
 *
 * @param stateDir Where the web client keeps its machine id.
 * @param hostname The name this phone shows to the other members.
 */
class EasyTierOverlayEngine(private val stateDir: File, private val hostname: String) : OverlayEngine {
    @Volatile
    private var isRunning = false
    private var worker: Thread? = null
    private var isConsole = false

    override fun start(
        overlay: ChannelOverlay,
        tun: TunBuilder,
        report: (OverlayPhase, String, ChannelResult.Refused?) -> Unit,
    ) {
        isRunning = true
        isConsole = overlay.easyTierMode == OVERLAY_EASYTIER_MODE_CONSOLE
        worker = thread(name = "easytier") { run(overlay, tun, report) }
    }

    override fun stop() {
        isRunning = false
        worker?.interrupt()
        try {
            if (isConsole) EasyTierJNI.stopWebClient() else EasyTierJNI.retainNetworkInstance(null)
        } catch (_: RuntimeException) {
            // The core had nothing running.
        }
        worker?.join(OVERLAY_POLL_MILLIS * 2)
    }

    private fun run(
        overlay: ChannelOverlay,
        tun: TunBuilder,
        report: (OverlayPhase, String, ChannelResult.Refused?) -> Unit,
    ) {
        report(OverlayPhase.JOINING, "", null)
        try {
            if (isConsole) {
                stateDir.mkdirs()
                EasyTierJNI.runWebClient(overlay.configServer, hostname, stateDir.path, overlay.isSecureMode)
            } else {
                EasyTierJNI.runNetworkInstance(EasyTierConfig.render(overlay, OVERLAY_EASYTIER_INSTANCE, hostname))
            }
        } catch (error: RuntimeException) {
            val code = if (isConsole) "overlay_console_invalid" else "overlay_join_failed"
            report(OverlayPhase.FAILED, "", ChannelResult.refused(code, "detail" to (error.message ?: "")))
            return
        }
        var built: Pair<String, List<String>>? = null
        while (isRunning) {
            val instance = try {
                EasyTierInstance.parse(EasyTierJNI.collectNetworkInfos()).firstOrNull { it.address.isNotEmpty() }
            } catch (_: RuntimeException) {
                null
            }
            val wanted = instance?.let { it.address to it.proxyCidrs }
            if (instance != null && wanted != built) {
                val routes = listOf(subnetOf(instance.address, instance.prefix)) + instance.proxyCidrs
                val fd = tun.establish(
                    instance.address,
                    instance.prefix,
                    OVERLAY_TUN_MTU,
                    routes,
                    emptyList(),
                    emptyList(),
                    false,
                )
                if (fd == null) {
                    report(OverlayPhase.FAILED, "", ChannelResult.refused("overlay_not_authorized"))
                    return
                }
                try {
                    EasyTierJNI.setTunFd(instance.name, fd)
                    built = wanted
                    report(OverlayPhase.ON, instance.address, null)
                } catch (error: RuntimeException) {
                    report(
                        OverlayPhase.FAILED,
                        "",
                        ChannelResult.refused(
                            "overlay_join_failed",
                            "detail" to (error.message ?: ""),
                        ),
                    )
                    return
                }
            }
            try {
                Thread.sleep(OVERLAY_POLL_MILLIS)
            } catch (_: InterruptedException) {
                break
            }
        }
        report(OverlayPhase.OFF, "", null)
    }

    private fun subnetOf(address: String, prefix: Int): String {
        val value = address.split('.').fold(0L) { total, part -> total * 256 + part.toLong() }
        val mask = if (prefix == 0) 0L else (0xffffffffL shl (32 - prefix)) and 0xffffffffL
        val network = value and mask
        return listOf(24, 16, 8, 0).joinToString(".") { ((network shr it) and 0xff).toString() } + "/$prefix"
    }
}
