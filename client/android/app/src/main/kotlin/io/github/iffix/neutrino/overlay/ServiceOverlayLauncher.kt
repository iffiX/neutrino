package io.github.iffix.neutrino.overlay

import android.content.Context

/**
 * Starts and stops [OverlayVpnService] by intent.
 *
 * @param context The app's context.
 */
class ServiceOverlayLauncher(private val context: Context) : OverlayLauncher {
    override fun start(bindingId: String, provider: String) {
        send { context.startService(OverlayVpnService.startIntent(context, bindingId, provider)) }
    }

    override fun stop() {
        send { context.startService(OverlayVpnService.stopIntent(context)) }
    }

    private fun send(action: () -> Unit) {
        try {
            action()
        } catch (_: IllegalStateException) {
            // A service cannot be started from the background; the next look starts it.
        } catch (_: SecurityException) {
            // The service is not the app's to start.
        }
    }
}
