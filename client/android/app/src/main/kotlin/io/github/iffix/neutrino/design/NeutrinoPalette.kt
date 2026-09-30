package io.github.iffix.neutrino.design

import androidx.compose.ui.graphics.Color

/**
 * One palette: the panel's colour tokens, under the names the panel's CSS gives them.
 *
 * Accent is what a screen is for and what is selected; ok is on and healthy; warn is a step in
 * flight or unsaved; error is failed and the destructive action. The signal colours carry no
 * text and draw the status dots.
 */
data class NeutrinoPalette(
    val bg: Color,
    val surface: Color,
    val elevated: Color,
    val border: Color,
    val borderStrong: Color,
    val text: Color,
    val textMuted: Color,
    val textFaint: Color,
    val accent: Color,
    val ok: Color,
    val warn: Color,
    val error: Color,
    val signalOk: Color,
    val signalWarn: Color,
    val signalError: Color,
    val shadow: Color,
    val termBg: Color,
    val termFg: Color,
    val isDark: Boolean,
) {
    /** The accent at 12 %, behind a selected or primary control. */
    val accentWash: Color get() = accent.copy(alpha = 0.12f)

    /** The error colour at 12 %, behind a destructive confirmation. */
    val errorWash: Color get() = error.copy(alpha = 0.12f)

    /** The ok colour at 12 %, behind a badge that reports on. */
    val okWash: Color get() = ok.copy(alpha = 0.12f)

    companion object {
        /** The dark palette. */
        val dark = NeutrinoPalette(
            bg = Color(0xFF070809),
            surface = Color(0xFF0E1013),
            elevated = Color(0xFF15181C),
            border = Color(0xFF1C2026),
            borderStrong = Color(0xFF2A3038),
            text = Color(0xFFE6EDF3),
            textMuted = Color(0xFF8B96A5),
            textFaint = Color(0xFF5B6675),
            accent = Color(0xFF22D3EE),
            ok = Color(0xFF34D399),
            warn = Color(0xFFFBBF24),
            error = Color(0xFFFB7185),
            signalOk = Color(0xFF34D399),
            signalWarn = Color(0xFFFBBF24),
            signalError = Color(0xFFFB7185),
            shadow = Color(0xE6000000),
            termBg = Color(0xFF070809),
            termFg = Color(0xFFE6EDF3),
            isDark = true,
        )

        /** The light palette. */
        val light = NeutrinoPalette(
            bg = Color(0xFFE8EBF0),
            surface = Color(0xFFF6F7F9),
            elevated = Color(0xFFDDE2E8),
            border = Color(0xFFCDD4DC),
            borderStrong = Color(0xFFB4BFCB),
            text = Color(0xFF0F172A),
            textMuted = Color(0xFF5B6675),
            textFaint = Color(0xFF7B8794),
            accent = Color(0xFF0C6A84),
            ok = Color(0xFF046A4D),
            warn = Color(0xFFA34A07),
            error = Color(0xFFB10F38),
            signalOk = Color(0xFF10B981),
            signalWarn = Color(0xFFF59E0B),
            signalError = Color(0xFFEF4444),
            shadow = Color(0x380F172A),
            termBg = Color(0xFF0F172A),
            termFg = Color(0xFFE6EDF3),
            isDark = false,
        )
    }
}
