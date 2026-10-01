package io.github.iffix.neutrino.remotedesktop

import android.os.Handler
import android.os.Looper
import android.view.Surface
import io.github.iffix.neutrino.RDP_STATE_CLOSED
import io.github.iffix.neutrino.RDP_STATE_CONNECTED
import io.github.iffix.neutrino.RDP_STATE_LOGIN_FAILED
import io.github.iffix.neutrino.channel.ChannelResult

/**
 * The RustDesk core built into the app: one direct session at a time, drawn straight into the
 * viewer's surface. Call it on the main thread.
 *
 * @param appDir Where the core keeps its configuration.
 */
class RustDeskRemoteDesktopCore(private val appDir: String) : RemoteDesktopCore {
    private val main = Handler(Looper.getMainLooper())
    private var state: RemoteDesktopState = RemoteDesktopState.Connecting
    private var session = 0
    private var isRunning = false

    override fun connect(
        target: RemoteDesktopTarget,
        onState: (RemoteDesktopState) -> Unit,
        onFrameSize: (Int, Int) -> Unit,
        onClipboard: (String) -> Unit,
    ) {
        if (isRunning) disconnect()
        if (!isInitialized) {
            RustDeskNative.init(appDir)
            isInitialized = true
        }
        val current = ++session
        state = RemoteDesktopState.Connecting
        isRunning = true
        val callbacks = object : RustDeskCallbacks {
            override fun onState(state: Int, text: String) {
                main.post {
                    if (current ==
                        session
                    ) {
                        advance(next(this@RustDeskRemoteDesktopCore.state, state, text), onState)
                    }
                }
            }

            override fun onSize(width: Int, height: Int) {
                main.post { if (current == session && isRunning) onFrameSize(width, height) }
            }

            override fun onClipboard(text: String) {
                main.post { if (current == session && isRunning) onClipboard(text) }
            }
        }
        val started = RustDeskNative.start(target.host, target.port, target.password, callbacks)
        if (started != 0) {
            advance(
                RemoteDesktopState.Stopped(ChannelResult.refused("rdp_launch_failed", "detail" to "$started")),
                onState,
            )
        }
    }

    override fun attach(surface: Surface?) = RustDeskNative.attach(surface)

    override fun mouse(event: RemoteDesktopMouse) {
        if (isRunning) RustDeskNative.mouse(event.x, event.y, event.mask)
    }

    override fun key(code: String, isDown: Boolean) {
        if (isRunning) RustDeskNative.key(code, isDown)
    }

    override fun type(text: String) {
        if (isRunning) RustDeskNative.text(text.toByteArray(Charsets.UTF_8))
    }

    override fun clipboard(text: String) {
        if (isRunning) RustDeskNative.clipboard(text.toByteArray(Charsets.UTF_8))
    }

    override fun disconnect() {
        session++
        if (!isRunning) return
        isRunning = false
        RustDeskNative.close()
    }

    private fun advance(next: RemoteDesktopState, onState: (RemoteDesktopState) -> Unit) {
        if (!isRunning || next == state) return
        state = next
        if (next is RemoteDesktopState.Stopped) {
            isRunning = false
            RustDeskNative.close()
        }
        onState(next)
    }

    companion object {
        private var isInitialized = false

        /**
         * Where a connection stands after one report of the core.
         *
         * @param current Where it stood.
         * @param state The core's report, one of the `RDP_STATE_` constants.
         * @param text Why it ended, in RustDesk's words.
         * @return The new standing; a stopped connection stays stopped.
         */
        fun next(current: RemoteDesktopState, state: Int, text: String): RemoteDesktopState = when {
            current is RemoteDesktopState.Stopped -> current

            state == RDP_STATE_CONNECTED -> RemoteDesktopState.Showing

            state == RDP_STATE_LOGIN_FAILED -> RemoteDesktopState.Stopped(ChannelResult.refused("rdp_login_failed"))

            state == RDP_STATE_CLOSED -> RemoteDesktopState.Stopped(
                ChannelResult.refused("rdp_closed", "reason" to text),
            )

            else -> current
        }
    }
}
