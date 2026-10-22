package io.github.iffix.neutrino.terminal

import io.github.iffix.neutrino.design.AppIcon

/**
 * One of the two round buttons at the left of the terminal's status line, drawn as the remote
 * desktop viewer's.
 *
 * @property wordKey The catalog key of its label.
 * @property icon What it shows.
 */
enum class TerminalControl(val wordKey: String, val icon: AppIcon) {
    KEYBOARD("ui.rdp_keyboard", AppIcon.KEYBOARD),
    KEYS("ui.rdp_keys", AppIcon.COMMAND),
    ;

    /**
     * Whether the button shows as active.
     *
     * @param isKeyboardShown Whether the system shows the keyboard, floating or not.
     * @param isKeyRowShown Whether the key row shows.
     * @return True for Keyboard while the keyboard is shown, and for Keys while the key row shows.
     */
    fun isActive(isKeyboardShown: Boolean, isKeyRowShown: Boolean): Boolean = when (this) {
        KEYBOARD -> isKeyboardShown
        KEYS -> isKeyRowShown
    }

    /**
     * What a press does: Keyboard raises or puts away the keyboard, Keys shows or hides the key row.
     *
     * @param isKeyboardShown Whether the system shows the keyboard.
     * @param isKeyRowShown Whether the key row shows.
     * @param onKeyboard Called with whether the keyboard is to be up.
     * @param onKeyRow Called with whether the key row is to show.
     */
    fun press(
        isKeyboardShown: Boolean,
        isKeyRowShown: Boolean,
        onKeyboard: (Boolean) -> Unit,
        onKeyRow: (Boolean) -> Unit,
    ) {
        when (this) {
            KEYBOARD -> onKeyboard(!isKeyboardShown)
            KEYS -> onKeyRow(!isKeyRowShown)
        }
    }
}
