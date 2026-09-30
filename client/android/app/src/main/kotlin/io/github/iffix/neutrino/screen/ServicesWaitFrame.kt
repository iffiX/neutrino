package io.github.iffix.neutrino.screen

import androidx.compose.runtime.Composable
import io.github.iffix.neutrino.design.AppIcon
import io.github.iffix.neutrino.design.NeutrinoButton
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.design.PlaceholderFrame

/**
 * What a service screen shows before any hub is joined: services appear once one is.
 *
 * @param onJoin What pressing Join a hub does.
 */
@Composable
fun ServicesWaitFrame(onJoin: () -> Unit) {
    val words = NeutrinoTheme.words
    PlaceholderFrame(
        line = words.word("ui.services_wait_join"),
        action = { NeutrinoButton(words.word("ui.add_hub"), onJoin, icon = AppIcon.PLUS) },
    )
}
