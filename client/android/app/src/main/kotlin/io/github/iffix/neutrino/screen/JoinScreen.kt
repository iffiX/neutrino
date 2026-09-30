package io.github.iffix.neutrino.screen

import androidx.compose.runtime.Composable
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.design.PlaceholderFrame
import io.github.iffix.neutrino.design.ScreenColumn

/** Joining a hub: the QR scanner, or the pasted link. */
@Composable
fun JoinScreen() {
    val words = NeutrinoTheme.words
    ScreenColumn {
        PlaceholderFrame(line = words.word("ui.paste_hint"), hint = words.word("ui.join_coming"))
    }
}
