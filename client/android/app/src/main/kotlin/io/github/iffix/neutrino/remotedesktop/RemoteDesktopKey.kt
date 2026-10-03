package io.github.iffix.neutrino.remotedesktop

/**
 * A key of the viewer's keyboard bar, by the name RustDesk gives it.
 *
 * @property label What the bar shows.
 * @property code RustDesk's name for the key.
 * @property isModifier Whether a press holds it for the next key rather than typing it.
 */
enum class RemoteDesktopKey(val label: String, val code: String, val isModifier: Boolean = false) {
    ESCAPE("Esc", "VK_ESCAPE"),
    TAB("Tab", "VK_TAB"),
    CTRL("Ctrl", "VK_CONTROL", isModifier = true),
    SHIFT("Shift", "VK_SHIFT", isModifier = true),
    ALT("Alt", "VK_MENU", isModifier = true),
    WIN("Win", "VK_LWIN", isModifier = true),
    LEFT("←", "VK_LEFT"),
    UP("↑", "VK_UP"),
    DOWN("↓", "VK_DOWN"),
    RIGHT("→", "VK_RIGHT"),
    ;

    companion object {
        /** RustDesk's name for Enter. */
        const val ENTER = "VK_RETURN"

        /** RustDesk's name for Backspace. */
        const val BACKSPACE = "VK_BACK"

        /** RustDesk's name for Delete. */
        const val DELETE = "VK_DELETE"

        /** RustDesk's name for the V that Ctrl turns into a paste. */
        const val PASTE = "VK_V"

        /**
         * RustDesk's name for a typed character that a held modifier applies to: a letter or a digit.
         *
         * @param character The character.
         * @return The key's name, or null for any other character.
         */
        fun codeOf(character: Char): String? = when (val upper = character.uppercaseChar()) {
            in 'A'..'Z', in '0'..'9' -> "VK_$upper"
            else -> null
        }
    }
}
