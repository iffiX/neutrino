package io.github.iffix.neutrino.remotedesktop

import io.github.iffix.neutrino.design.AppIcon

/**
 * One of the three round buttons at the viewer's top right.
 *
 * @property wordKey The catalog key of its label.
 * @property icon What it shows.
 * @property isDanger Whether it is drawn in the danger tone.
 */
enum class RemoteDesktopButton(val wordKey: String, val icon: AppIcon, val isDanger: Boolean = false) {
    KEYBOARD("ui.rdp_keyboard", AppIcon.KEYBOARD),
    KEYS("ui.rdp_keys", AppIcon.COMMAND),
    CLOSE("ui.rdp_disconnect", AppIcon.CLOSE, isDanger = true),
    ;

    /**
     * Whether the button shows as active.
     *
     * @param keyboard The phone's keyboard.
     * @param isKeyBarShown Whether the key bar shows.
     * @return True for Keyboard while the system shows the keyboard, floating or not, and for Keys
     *     while the key bar shows.
     */
    fun isActive(keyboard: RemoteDesktopKeyboard, isKeyBarShown: Boolean): Boolean = when (this) {
        KEYBOARD -> keyboard.isShown
        KEYS -> isKeyBarShown
        CLOSE -> false
    }

    /**
     * What a press does: Keyboard raises or puts away the keyboard, Keys shows or hides the key
     * bar, Close ends the session.
     *
     * @param keyboard The phone's keyboard.
     * @param isKeyBarShown Whether the key bar shows.
     * @param onKeyboard Called with whether the keyboard is to be up.
     * @param onKeyBar Called with whether the key bar is to show.
     * @param onClose Called to end the session.
     */
    fun press(
        keyboard: RemoteDesktopKeyboard,
        isKeyBarShown: Boolean,
        onKeyboard: (Boolean) -> Unit,
        onKeyBar: (Boolean) -> Unit,
        onClose: () -> Unit,
    ) {
        when (this) {
            KEYBOARD -> onKeyboard(!isActive(keyboard, isKeyBarShown))
            KEYS -> onKeyBar(!isKeyBarShown)
            CLOSE -> onClose()
        }
    }
}
