package io.github.iffix.neutrino.remotedesktop

/**
 * The phone's keyboard as the viewer sees it. A keyboard the system floats over the picture is
 * shown and covers no height.
 *
 * @property isShown Whether the system shows the keyboard.
 * @property height The height in pixels it covers at the bottom edge, 0 for a floating keyboard or none.
 */
data class RemoteDesktopKeyboard(val isShown: Boolean, val height: Int) {
    /** Whether the viewer's hidden input keeps the focus: while the keyboard is shown. */
    val isFocusKept: Boolean
        get() = isShown
}
