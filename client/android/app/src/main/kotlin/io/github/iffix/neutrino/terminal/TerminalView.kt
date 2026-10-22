package io.github.iffix.neutrino.terminal

import android.annotation.SuppressLint
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.util.Base64
import android.view.inputmethod.InputMethodManager
import android.webkit.JavascriptInterface
import android.webkit.WebView
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import io.github.iffix.neutrino.CLIENT_TERMINAL_BRIDGE
import io.github.iffix.neutrino.CLIENT_TERMINAL_PAGE
import io.github.iffix.neutrino.design.NeutrinoPalette
import java.util.concurrent.ConcurrentHashMap
import org.json.JSONArray
import org.json.JSONObject

/**
 * The WebView the terminals are drawn in: xterm.js from the app's assets, one pane per tab, each
 * scrolled by touch with a thin bar, and a long press opening Copy, Paste, Select all and Clear
 * through the system clipboard. While a tab's Clear drops output its pane draws nothing that
 * arrives, written before the Clear or after it; the pane is wiped when the drop starts and when
 * it ends, and leaves the clearing state when the Clear is refused or the shell ends.
 *
 * @param context The window's context.
 * @param tabs The tabs whose output it draws and whose input it sends.
 * @param onModifiersUsed Called on the main thread once the held modifiers were spent on a typed key.
 */
@SuppressLint("SetJavaScriptEnabled", "ViewConstructor")
class TerminalView(context: Context, private val tabs: TerminalTabs, private val onModifiersUsed: () -> Unit) :
    WebView(context) {
    private val opened = mutableSetOf<String>()
    private val clipboard = context.getSystemService(ClipboardManager::class.java)
    private val clearCounts = ConcurrentHashMap<String, Int>()
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
     * Hold the key row's modifiers for the next typed key.
     *
     * @param held The modifiers held.
     */
    fun modifiers(held: TerminalModifiers) {
        val json = JSONObject().put("ctrl", held.isCtrl).put("shift", held.isShift).put("alt", held.isAlt)
        run { call("neutrino.modifiers(${JSONObject.quote(json.toString())})") }
    }

    /**
     * Draw the terminals and the page around them in one palette.
     *
     * @param palette The palette.
     */
    fun palette(palette: NeutrinoPalette) {
        val colors = TerminalTheme.of(palette)
        val theme = JSONObject().put("terminal", JSONObject(colors.terminal)).put("chrome", JSONObject(colors.chrome))
        run { call("neutrino.theme(${JSONObject.quote(theme.toString())})") }
    }

    /**
     * Word the long press menu.
     *
     * @param copy Copy's label.
     * @param paste Paste's label.
     * @param selectAll Select all's label.
     * @param clear Clear's label.
     * @param clearing The word a pane shows while its Clear drops output.
     */
    fun labels(copy: String, paste: String, selectAll: String, clear: String, clearing: String) {
        val labels = JSONObject()
            .put("copy", copy)
            .put("paste", paste)
            .put("selectAll", selectAll)
            .put("clear", clear)
            .put("clearing", clearing)
        run { call("neutrino.labels(${JSONObject.quote(labels.toString())})") }
    }

    /**
     * Show the clearing word on the panes whose Clear is dropping output, and on no other.
     *
     * @param sessionIds The tabs still dropping.
     */
    fun clearing(sessionIds: Set<String>) {
        val ids = JSONArray(sessionIds.toList()).toString()
        run { call("neutrino.clearing(${JSONObject.quote(ids)})") }
    }

    /** Give the shown pane the focus and raise the phone's keyboard, as a tap on the pane does. */
    fun showKeyboard() {
        requestFocus()
        run { call("neutrino.focus()") }
        post { context.getSystemService(InputMethodManager::class.java)?.showSoftInput(this, 0) }
    }

    /** Put the phone's keyboard away. */
    fun hideKeyboard() {
        context.getSystemService(InputMethodManager::class.java)?.hideSoftInputFromWindow(windowToken, 0)
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

    private inner class Bridge {
        @JavascriptInterface
        fun ready() {
            post {
                isReady = true
                pending?.invoke()
                pending = null
                tabs.watch { id, bytes ->
                    val encoded = Base64.encodeToString(bytes, Base64.NO_WRAP)
                    val clears = clearCounts[id] ?: 0
                    post { if ((clearCounts[id] ?: 0) == clears) call("neutrino.write('$id','$encoded')") }
                }
            }
        }

        @JavascriptInterface
        fun input(sessionId: String, encoded: String) {
            tabs.input(sessionId, Base64.decode(encoded, Base64.DEFAULT))
        }

        @JavascriptInterface
        fun clear(sessionId: String): Boolean {
            clearCounts.merge(sessionId, 1, Int::plus)
            return tabs.clear(sessionId)
        }

        @JavascriptInterface
        fun resize(sessionId: String, cols: Int, rows: Int) {
            tabs.sized(sessionId, cols, rows)
        }

        @JavascriptInterface
        fun modifiersUsed() {
            post(onModifiersUsed)
        }

        @JavascriptInterface
        fun copy(text: String) {
            if (text.isEmpty()) return
            post { clipboard.setPrimaryClip(ClipData.newPlainText("", text)) }
        }

        @JavascriptInterface
        fun paste(): String = clipboard.primaryClip?.takeIf {
            it.itemCount > 0
        }?.getItemAt(0)?.coerceToText(context)?.toString().orEmpty()
    }
}
