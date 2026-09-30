package io.github.iffix.neutrino.terminal

import android.annotation.SuppressLint
import android.content.Context
import android.util.Base64
import android.webkit.JavascriptInterface
import android.webkit.WebView
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import io.github.iffix.neutrino.CLIENT_TERMINAL_BRIDGE
import io.github.iffix.neutrino.CLIENT_TERMINAL_PAGE
import io.github.iffix.neutrino.design.NeutrinoPalette
import org.json.JSONObject

/**
 * The WebView the terminals are drawn in: xterm.js from the app's assets, one pane per tab.
 *
 * @param context The window's context.
 * @param tabs The tabs whose output it draws and whose input it sends.
 * @param onCtrlUsed Called on the main thread once a held Ctrl was spent on a key.
 */
@SuppressLint("SetJavaScriptEnabled", "ViewConstructor")
class TerminalView(context: Context, private val tabs: TerminalTabs, private val onCtrlUsed: () -> Unit) :
    WebView(context) {
    private val opened = mutableSetOf<String>()
    private var isReady = false
    private var pending: (() -> Unit)? = null

    init {
        settings.javaScriptEnabled = true
        setBackgroundColor(Color.Transparent.toArgb())
        addJavascriptInterface(Bridge(), CLIENT_TERMINAL_BRIDGE)
        loadUrl(CLIENT_TERMINAL_PAGE)
    }

    /**
     * Show one tab's pane, making it first when the page has none for it.
     *
     * @param sessionId The tab, or empty for none.
     */
    fun show(sessionId: String) {
        run {
            if (sessionId.isNotEmpty() && opened.add(sessionId)) call("neutrino.open('$sessionId')")
            call("neutrino.show('$sessionId')")
        }
    }

    /**
     * Keep one pane per tab: make the missing ones and drop the ones whose tab is gone.
     *
     * @param live The tabs that exist.
     */
    fun panes(live: Set<String>) {
        run {
            for (gone in opened - live) call("neutrino.close('$gone')")
            opened.retainAll(live)
            for (id in live) if (opened.add(id)) call("neutrino.open('$id')")
        }
    }

    /**
     * Hold or release Ctrl for the next key.
     *
     * @param isHeld Whether Ctrl is held.
     */
    fun ctrl(isHeld: Boolean) = run { call("neutrino.ctrl($isHeld)") }

    /**
     * Draw the terminals in one palette.
     *
     * @param palette The palette.
     */
    fun palette(palette: NeutrinoPalette) {
        val theme = JSONObject()
            .put("background", hex(palette.termBg))
            .put("foreground", hex(palette.termFg))
            .put("cursor", hex(palette.accent))
            .put("cursorAccent", hex(palette.termBg))
            .put("selectionBackground", hex(palette.accent) + "40")
            .put("red", hex(palette.signalError))
            .put("green", hex(palette.signalOk))
            .put("yellow", hex(palette.signalWarn))
            .put("blue", hex(palette.accent))
            .put("cyan", hex(palette.accent))
        run { call("neutrino.theme(${JSONObject.quote(theme.toString())})") }
    }

    /** Stop drawing output; the tabs keep it for the next view. */
    fun detach() {
        tabs.watch(null)
        removeJavascriptInterface(CLIENT_TERMINAL_BRIDGE)
        destroy()
    }

    private fun run(action: () -> Unit) {
        post {
            if (isReady) {
                action()
            } else {
                val before = pending
                pending = {
                    before?.invoke()
                    action()
                }
            }
        }
    }

    private fun call(script: String) = evaluateJavascript(script, null)

    private fun hex(color: Color): String = "#%06x".format(color.toArgb() and 0xffffff)

    private inner class Bridge {
        @JavascriptInterface
        fun ready() {
            post {
                isReady = true
                pending?.invoke()
                pending = null
                tabs.watch { id, bytes ->
                    val encoded = Base64.encodeToString(bytes, Base64.NO_WRAP)
                    post { call("neutrino.write('$id','$encoded')") }
                }
            }
        }

        @JavascriptInterface
        fun input(sessionId: String, encoded: String) {
            tabs.input(sessionId, Base64.decode(encoded, Base64.DEFAULT))
        }

        @JavascriptInterface
        fun resize(sessionId: String, cols: Int, rows: Int) {
            tabs.sized(sessionId, cols, rows)
        }

        @JavascriptInterface
        fun ctrlUsed() {
            post(onCtrlUsed)
        }
    }
}
