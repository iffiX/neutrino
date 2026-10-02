package io.github.iffix.neutrino.terminal

import io.github.iffix.neutrino.TERMINAL_ESCAPE

/**
 * A key of the row above the keyboard, in the row's order.
 *
 * @property label What the row shows.
 * @property isModifier Whether a press holds it for the next key rather than sending it.
 */
enum class TerminalKey(val label: String, val isModifier: Boolean = false) {
    ESCAPE("Esc"),
    TAB("Tab"),
    CTRL("Ctrl", isModifier = true),
    SHIFT("Shift", isModifier = true),
    ALT("Alt", isModifier = true),
    LEFT("←"),
    UP("↑"),
    DOWN("↓"),
    RIGHT("→"),
    ;

    /**
     * What the key sends to the shell with the held modifiers, as xterm encodes it: Alt puts
     * Escape before Esc and Tab, Shift turns Tab into back-tab, and an arrow carries every
     * modifier in its parameter.
     *
     * @param modifiers The modifiers held.
     * @return The bytes' text; empty for a modifier.
     */
    fun sequence(modifiers: TerminalModifiers): String {
        val alt = if (modifiers.isAlt) TERMINAL_ESCAPE else ""
        return when (this) {
            ESCAPE -> alt + TERMINAL_ESCAPE
            TAB -> alt + if (modifiers.isShift) "$TERMINAL_ESCAPE[Z" else "\t"
            LEFT -> arrow('D', modifiers)
            UP -> arrow('A', modifiers)
            DOWN -> arrow('B', modifiers)
            RIGHT -> arrow('C', modifiers)
            CTRL, SHIFT, ALT -> ""
        }
    }

    private fun arrow(letter: Char, modifiers: TerminalModifiers): String {
        val parameter = modifiers.xtermParameter
        return if (parameter == 1) "$TERMINAL_ESCAPE[$letter" else "$TERMINAL_ESCAPE[1;$parameter$letter"
    }
}
