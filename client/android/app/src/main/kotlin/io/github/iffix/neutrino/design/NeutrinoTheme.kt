package io.github.iffix.neutrino.design

import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import io.github.iffix.neutrino.words.WordCatalog

private val LocalPalette = staticCompositionLocalOf { NeutrinoPalette.dark }
private val LocalWords = staticCompositionLocalOf { WordCatalog(emptyMap()) }

/**
 * Provide the palette and the words every component below reads.
 *
 * @param palette The palette in force.
 * @param words The catalog of the language in force.
 * @param content The screens.
 */
@Composable
fun NeutrinoTheme(palette: NeutrinoPalette, words: WordCatalog, content: @Composable () -> Unit) {
    CompositionLocalProvider(LocalPalette provides palette, LocalWords provides words, content = content)
}

/** What a composable reads of the theme in force. */
object NeutrinoTheme {
    /** The palette in force. */
    val palette: NeutrinoPalette
        @Composable @ReadOnlyComposable
        get() = LocalPalette.current

    /** The words of the language in force. */
    val words: WordCatalog
        @Composable @ReadOnlyComposable
        get() = LocalWords.current

    /** Prose: the default text of a screen. */
    val body: TextStyle
        @Composable @ReadOnlyComposable
        get() = TextStyle(color = palette.text, fontSize = 14.sp, lineHeight = 21.sp, fontFamily = FontFamily.SansSerif)

    /** The top bar's page title. */
    val pageTitle: TextStyle
        @Composable @ReadOnlyComposable
        get() = body.copy(fontSize = 15.sp, fontWeight = FontWeight.SemiBold)

    /** A row's title. */
    val rowTitle: TextStyle
        @Composable @ReadOnlyComposable
        get() = body.copy(fontWeight = FontWeight.SemiBold)

    /** A row's second line: provenance, a hint, a state word. */
    val note: TextStyle
        @Composable @ReadOnlyComposable
        get() = body.copy(color = palette.textMuted, fontSize = 12.sp, lineHeight = 18.sp)

    /** An address, a name, a count: the mono face. */
    val mono: TextStyle
        @Composable @ReadOnlyComposable
        get() = note.copy(fontFamily = FontFamily.Monospace)

    /** A field's label. */
    val fieldLabel: TextStyle
        @Composable @ReadOnlyComposable
        get() = note.copy(fontWeight = FontWeight.Medium)

    /** A button's label. */
    val buttonLabel: TextStyle
        @Composable @ReadOnlyComposable
        get() = body.copy(fontSize = 13.sp, fontWeight = FontWeight.Medium)

    /** A badge: one mono word. */
    val badge: TextStyle
        @Composable @ReadOnlyComposable
        get() = mono.copy(fontSize = 11.sp, lineHeight = 16.sp)

    /**
     * The same style in another colour.
     *
     * @param style The style.
     * @param color The colour.
     * @return The style drawn in that colour.
     */
    fun tinted(style: TextStyle, color: Color): TextStyle = style.copy(color = color)
}
