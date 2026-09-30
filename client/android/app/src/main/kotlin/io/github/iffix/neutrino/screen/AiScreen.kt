package io.github.iffix.neutrino.screen

import androidx.compose.runtime.Composable
import io.github.iffix.neutrino.design.ScreenColumn

/**
 * The AI gateway a joined hub publishes, with this phone's key.
 *
 * @param onJoin What pressing Join a hub does.
 */
@Composable
fun AiScreen(onJoin: () -> Unit) {
    ScreenColumn {
        ServicesWaitFrame(onJoin)
    }
}
