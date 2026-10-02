package io.github.iffix.neutrino.design

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

class SelectedMarkTest {
    @Test
    fun theSelectedOneWearsTheAccentOnTheElevatedSurface() {
        for (palette in listOf(NeutrinoPalette.dark, NeutrinoPalette.light)) {
            val mark = SelectedMark.of(palette, isSelected = true)
            assertEquals(palette.accent, mark.border)
            assertEquals(palette.accent, mark.text)
            assertEquals(palette.elevated, mark.fill)
        }
    }

    @Test
    fun theOthersHaveThePlainBorder() {
        for (palette in listOf(NeutrinoPalette.dark, NeutrinoPalette.light)) {
            val mark = SelectedMark.of(palette, isSelected = false)
            assertEquals(palette.border, mark.border)
            assertEquals(palette.surface, mark.fill)
            assertNotEquals(palette.accent, mark.text)
        }
    }
}
