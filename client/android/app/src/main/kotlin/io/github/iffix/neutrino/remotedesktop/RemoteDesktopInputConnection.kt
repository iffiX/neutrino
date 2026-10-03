package io.github.iffix.neutrino.remotedesktop

import android.text.Editable
import android.view.KeyEvent
import android.view.View
import android.view.inputmethod.BaseInputConnection

/**
 * The phone keyboard's link to the viewer. Committed text is sent as text; text still being
 * composed is sent nowhere until the keyboard finishes it, and then once as text; a commit
 * replaces the composition; a delete is sent as Backspaces and Deletes; Enter, Backspace, Tab and
 * the arrows are sent as their keys, and an editor action as Enter.
 *
 * @param view The view the keyboard types into.
 * @param sender Where the keys and the text go.
 */
class RemoteDesktopInputConnection(view: View, private val sender: RemoteDesktopInputSender) :
    BaseInputConnection(view, true) {
    private var composing: String = ""

    override fun commitText(text: CharSequence?, newCursorPosition: Int): Boolean {
        dropComposition()
        if (!text.isNullOrEmpty()) sender.type(text.toString())
        return true
    }

    override fun setComposingText(text: CharSequence?, newCursorPosition: Int): Boolean {
        composing = text?.toString().orEmpty()
        super.setComposingText(text, newCursorPosition)
        return true
    }

    override fun finishComposingText(): Boolean {
        val finished = composing
        dropComposition()
        if (finished.isNotEmpty()) sender.type(finished)
        return true
    }

    override fun deleteSurroundingText(beforeLength: Int, afterLength: Int): Boolean {
        repeat(beforeLength) { sender.press(RemoteDesktopKey.BACKSPACE) }
        repeat(afterLength) { sender.press(RemoteDesktopKey.DELETE) }
        return true
    }

    override fun deleteSurroundingTextInCodePoints(beforeLength: Int, afterLength: Int): Boolean =
        deleteSurroundingText(beforeLength, afterLength)

    override fun sendKeyEvent(event: KeyEvent): Boolean {
        when (event.action) {
            KeyEvent.ACTION_DOWN -> keyDown(event.keyCode, event.unicodeChar)
            KeyEvent.ACTION_MULTIPLE -> event.characters?.let { commitText(it, 1) }
        }
        return true
    }

    override fun performEditorAction(editorAction: Int): Boolean {
        sender.press(RemoteDesktopKey.ENTER)
        return true
    }

    /**
     * A key pressed on the keyboard: Enter, Backspace, Delete, Tab and the arrows are sent as their
     * keys, a printable character as committed text, and any other key is dropped.
     *
     * @param keyCode Android's code for the key.
     * @param character The character the key types, or 0 for none.
     */
    fun keyDown(keyCode: Int, character: Int) {
        val code = when (keyCode) {
            KeyEvent.KEYCODE_ENTER, KeyEvent.KEYCODE_NUMPAD_ENTER -> RemoteDesktopKey.ENTER
            KeyEvent.KEYCODE_DEL -> RemoteDesktopKey.BACKSPACE
            KeyEvent.KEYCODE_FORWARD_DEL -> RemoteDesktopKey.DELETE
            KeyEvent.KEYCODE_TAB -> RemoteDesktopKey.TAB.code
            KeyEvent.KEYCODE_DPAD_LEFT -> RemoteDesktopKey.LEFT.code
            KeyEvent.KEYCODE_DPAD_UP -> RemoteDesktopKey.UP.code
            KeyEvent.KEYCODE_DPAD_RIGHT -> RemoteDesktopKey.RIGHT.code
            KeyEvent.KEYCODE_DPAD_DOWN -> RemoteDesktopKey.DOWN.code
            else -> null
        }
        when {
            code != null -> sender.press(code)
            character > 0 -> commitText(String(Character.toChars(character)), 1)
        }
    }

    private fun dropComposition() {
        composing = ""
        editable?.let { content: Editable ->
            removeComposingSpans(content)
            content.clear()
        }
    }
}
