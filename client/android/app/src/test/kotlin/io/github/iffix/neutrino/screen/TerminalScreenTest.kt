package io.github.iffix.neutrino.screen

import androidx.compose.ui.unit.dp
import io.github.iffix.neutrino.CLIENT_TERMINAL_CARD_IME_MIN_HEIGHT_DP
import io.github.iffix.neutrino.CLIENT_TERMINAL_CARD_MIN_HEIGHT_DP
import org.junit.Assert.assertEquals
import org.junit.Test

class TerminalScreenTest {
    @Test
    fun aTallWindowGivesTheCardItsHeightLessTheGutters() {
        assertEquals(768.dp, terminalCardHeight(800.dp, isImeShown = false))
    }

    @Test
    fun withTheKeyboardShownTheCardShrinksToTheSpaceLeft() {
        assertEquals(318.dp, terminalCardHeight(350.dp, isImeShown = true))
    }

    @Test
    fun aShortWindowScrollsRatherThanSqueezeTheCard() {
        assertEquals(CLIENT_TERMINAL_CARD_MIN_HEIGHT_DP.dp, terminalCardHeight(350.dp, isImeShown = false))
    }

    @Test
    fun withTheKeyboardShownTheCardKeepsItsSmallerMinimum() {
        assertEquals(CLIENT_TERMINAL_CARD_IME_MIN_HEIGHT_DP.dp, terminalCardHeight(120.dp, isImeShown = true))
    }
}
