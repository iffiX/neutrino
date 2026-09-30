package io.github.iffix.neutrino.screen

import androidx.compose.runtime.Composable
import io.github.iffix.neutrino.design.ScreenColumn

/**
 * The desktops the machines of the joined hubs share.
 *
 * @param onJoin What pressing Join a hub does.
 */
@Composable
fun RemoteDesktopScreen(onJoin: () -> Unit) {
    ScreenColumn {
        ServicesWaitFrame(onJoin)
    }
}
