package io.github.iffix.neutrino.screen

import androidx.compose.runtime.Composable
import io.github.iffix.neutrino.design.ScreenColumn

/**
 * The terminals of the machines the joined hubs manage.
 *
 * @param onJoin What pressing Join a hub does.
 */
@Composable
fun TerminalScreen(onJoin: () -> Unit) {
    ScreenColumn {
        ServicesWaitFrame(onJoin)
    }
}
