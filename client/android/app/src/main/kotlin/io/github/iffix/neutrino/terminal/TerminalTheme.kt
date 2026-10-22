package io.github.iffix.neutrino.terminal

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import io.github.iffix.neutrino.CLIENT_TERMINAL_ANSI_COLORS
import io.github.iffix.neutrino.design.NeutrinoPalette

/**
 * The colours the terminal page draws in for one palette, as `#rrggbb` or `#rrggbbaa`.
 *
 * @property terminal xterm.js's theme: the default background and foreground, the cursor and the
 *     selection from the palette, and the sixteen ANSI colours of [CLIENT_TERMINAL_ANSI_COLORS],
 *     the same in every palette.
 * @property chrome The page's colours around the terminals: the scroll bar, the clearing word and
 *     the long press menu, by their CSS custom property names.
 */
data class TerminalTheme(val terminal: Map<String, String>, val chrome: Map<String, String>) {
    companion object {
        /**
         * The terminal page's colours in a palette.
         *
         * @param palette The palette in force.
         * @return Its colours.
         */
        fun of(palette: NeutrinoPalette): TerminalTheme = TerminalTheme(
            terminal = linkedMapOf(
                "background" to hex(palette.bg),
                "foreground" to hex(palette.text),
                "cursor" to hex(palette.accent),
                "cursorAccent" to hex(palette.bg),
                "selectionBackground" to hex(palette.accent) + "40",
            ) + CLIENT_TERMINAL_ANSI_COLORS,
            chrome = linkedMapOf(
                "bar" to hex(palette.textMuted),
                "note" to hex(palette.textMuted),
                "menu-ground" to hex(palette.bg),
                "menu-border" to hex(palette.border),
                "menu-text" to hex(palette.text),
                "menu-faint" to hex(palette.textFaint),
                "menu-lift" to hex(palette.elevated),
                "menu-accent" to hex(palette.accent),
                "menu-shadow" to hex(palette.shadow),
            ),
        )

        private fun hex(color: Color): String = "#%06x".format(color.toArgb() and 0xffffff)
    }
}
