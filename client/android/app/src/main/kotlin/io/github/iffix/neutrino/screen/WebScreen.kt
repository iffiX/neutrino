package io.github.iffix.neutrino.screen

import androidx.compose.runtime.Composable
import io.github.iffix.neutrino.design.ScreenColumn

/**
 * The web services the joined hubs publish, each opened in the browser.
 *
 * @param onJoin What pressing Join a hub does.
 */
@Composable
fun WebScreen(onJoin: () -> Unit) {
    ScreenColumn {
        ServicesWaitFrame(onJoin)
    }
}
