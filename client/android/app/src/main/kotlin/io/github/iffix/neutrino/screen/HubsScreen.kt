package io.github.iffix.neutrino.screen

import androidx.compose.runtime.Composable
import io.github.iffix.neutrino.design.AppIcon
import io.github.iffix.neutrino.design.ButtonTier
import io.github.iffix.neutrino.design.NeutrinoButton
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.design.PlaceholderFrame
import io.github.iffix.neutrino.design.ScreenColumn

/**
 * The hubs this phone has joined, each with its virtual network, and the way to join another.
 *
 * @param onJoin What pressing Join a hub does.
 */
@Composable
fun HubsScreen(onJoin: () -> Unit) {
    val words = NeutrinoTheme.words
    ScreenColumn {
        PlaceholderFrame(
            line = words.word("ui.no_hubs"),
            hint = words.word("ui.join_hint"),
            action = {
                NeutrinoButton(words.word("ui.add_hub"), onJoin, tier = ButtonTier.PRIMARY, icon = AppIcon.PLUS)
            },
        )
    }
}
