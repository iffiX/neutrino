package io.github.iffix.neutrino.screen

import androidx.compose.runtime.Composable
import io.github.iffix.neutrino.design.ScreenColumn

/**
 * The ports the joined hubs publish, each with its address to copy.
 *
 * @param onJoin What pressing Join a hub does.
 */
@Composable
fun PortsScreen(onJoin: () -> Unit) {
    ScreenColumn {
        ServicesWaitFrame(onJoin)
    }
}
