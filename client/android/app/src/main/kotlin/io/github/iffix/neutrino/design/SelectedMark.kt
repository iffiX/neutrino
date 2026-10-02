package io.github.iffix.neutrino.design

import androidx.compose.ui.graphics.Color

/**
 * How a chip or a tab is drawn picked or not, as the panel marks its selected chip: the accent
 * as the border and the text, the elevated surface as the fill; a plain one has the plain border.
 *
 * @property border The border's colour.
 * @property text The label's colour.
 * @property fill The ground's colour.
 */
data class SelectedMark(val border: Color, val text: Color, val fill: Color) {
    companion object {
        /**
         * The mark of one chip or tab.
         *
         * @param palette The palette in force.
         * @param isSelected Whether it is the picked one.
         * @return Its colours.
         */
        fun of(palette: NeutrinoPalette, isSelected: Boolean): SelectedMark = if (isSelected) {
            SelectedMark(border = palette.accent, text = palette.accent, fill = palette.elevated)
        } else {
            SelectedMark(border = palette.border, text = palette.textMuted, fill = palette.surface)
        }
    }
}
