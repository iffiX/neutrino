package io.github.iffix.neutrino.remotedesktop

import android.text.Editable
import android.view.KeyEvent
import android.view.View
import android.view.inputmethod.BaseInputConnection

/**
 * The phone keyboard's link to the viewer. Committed text is sent as text; text still being
 * composed stays in the keyboard and is sent nowhere; a delete is sent as Backspaces and Deletes;
 * Enter, Backspace, Tab and the arrows are sent as their keys.
 *
 * @param view The view the keyboard types into.
 * @param sender Where the keys and the text go.
 */
class RemoteDesktopInputConnection(view: View, private val sender: RemoteDesktopInputSender) :
    BaseInputConnection(view, true) {
    override fun commitText(text: CharSequence?, newCursorPosition: Int): Boolean {
        editable?.let(::empty)
        if (!text.isNullOrEmpty()) sender.type(text.toString())
        return true
    }

    override fun finishComposingText(): Boolean {
        editable?.let(::empty)
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

    override fun performEditorAction(editorAction: Int): Boolean = true

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

    private fun empty(content: Editable) {
        removeComposingSpans(content)
        content.clear()
    }
}
