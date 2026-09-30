package io.github.iffix.neutrino.screen

import androidx.compose.runtime.Composable
import io.github.iffix.neutrino.design.ScreenColumn

/**
 * The shares the joined hubs publish, each a place in the system's Files.
 *
 * @param onJoin What pressing Join a hub does.
 */
@Composable
fun FilesScreen(onJoin: () -> Unit) {
    ScreenColumn {
        ServicesWaitFrame(onJoin)
    }
}
