package io.github.iffix.neutrino.remotedesktop

import android.content.Context
import android.graphics.Rect
import android.text.InputType
import android.view.View
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputConnection
import android.view.inputmethod.InputMethodManager

/**
 * The invisible view the phone's keyboard types into while the viewer takes typing. It keeps the
 * focus from [showKeyboard] until [hideKeyboard].
 *
 * @param context The viewer's context.
 */
class RemoteDesktopInputView(context: Context) : View(context) {
    /** Where the keys and the text go; the keyboard gets no connection while it is null. */
    var sender: RemoteDesktopInputSender? = null

    /** Whether the view takes the focus back each time it loses it. */
    var isHoldingFocus: Boolean = false
        private set

    init {
        isFocusable = true
        isFocusableInTouchMode = true
    }

    override fun onCheckIsTextEditor(): Boolean = true

    override fun onCreateInputConnection(outAttrs: EditorInfo): InputConnection? {
        outAttrs.inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
        outAttrs.imeOptions = EditorInfo.IME_ACTION_NONE or EditorInfo.IME_FLAG_NO_FULLSCREEN
        return sender?.let { RemoteDesktopInputConnection(this, it) }
    }

    override fun onWindowFocusChanged(hasWindowFocus: Boolean) {
        super.onWindowFocusChanged(hasWindowFocus)
        if (hasWindowFocus) holdFocus()
    }

    override fun onFocusChanged(gainFocus: Boolean, direction: Int, previouslyFocusedRect: Rect?) {
        super.onFocusChanged(gainFocus, direction, previouslyFocusedRect)
        if (!gainFocus) post { holdFocus() }
    }

    /** Take the focus and raise the phone's keyboard. */
    fun showKeyboard() {
        isHoldingFocus = true
        requestFocus()
        context.getSystemService(InputMethodManager::class.java)?.showSoftInput(this, 0)
    }

    /** Put the phone's keyboard away and let the focus go. */
    fun hideKeyboard() {
        isHoldingFocus = false
        context.getSystemService(InputMethodManager::class.java)?.hideSoftInputFromWindow(windowToken, 0)
        clearFocus()
    }

    /** Let the focus go without touching the keyboard, once the keyboard is down. */
    fun releaseFocus() {
        isHoldingFocus = false
    }

    /** Take the focus back while the view holds it. */
    fun holdFocus() {
        if (isHoldingFocus && !isFocused) requestFocus()
    }
}
