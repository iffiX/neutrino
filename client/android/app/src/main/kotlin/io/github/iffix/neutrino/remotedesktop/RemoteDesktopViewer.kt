package io.github.iffix.neutrino.remotedesktop

import android.view.SurfaceHolder
import android.view.SurfaceView
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.text.BasicText
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import io.github.iffix.neutrino.design.AppIcon
import io.github.iffix.neutrino.design.ButtonTier
import io.github.iffix.neutrino.design.DotTone
import io.github.iffix.neutrino.design.NeutrinoButton
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.design.StatusDot

/**
 * The viewer over the whole window: a bar with the machine's name, Keyboard and Disconnect, and
 * below it the surface the core draws into and takes touches from. Without a core it stays dark
 * and says so.
 *
 * @param target The desktop to show.
 * @param core What decodes the picture and sends the input.
 * @param onClose What Disconnect and Back do.
 */
@Composable
fun RemoteDesktopViewer(target: RemoteDesktopTarget, core: RemoteDesktopCore, onClose: () -> Unit) {
    val words = NeutrinoTheme.words
    val palette = NeutrinoTheme.palette
    var state by remember(target) { mutableStateOf<RemoteDesktopState>(RemoteDesktopState.Connecting) }
    val focus = remember { FocusRequester() }
    val keyboard = LocalSoftwareKeyboardController.current
    BackHandler(onBack = onClose)
    DisposableEffect(target, core) { onDispose { core.disconnect() } }
    Column(modifier = Modifier.fillMaxSize().background(palette.bg).statusBarsPadding().imePadding()) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            BasicText(
                target.name,
                modifier = Modifier.weight(1f),
                style = NeutrinoTheme.rowTitle,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            NeutrinoButton(
                label = words.word("ui.rdp_keyboard"),
                onClick = {
                    focus.requestFocus()
                    keyboard?.show()
                },
                icon = AppIcon.KEYBOARD,
                isEnabled = state == RemoteDesktopState.Showing,
                isSmall = true,
            )
            NeutrinoButton(
                label = words.word("ui.rdp_disconnect"),
                onClick = onClose,
                tier = ButtonTier.DANGER,
                isSmall = true,
            )
        }
        Box(modifier = Modifier.weight(1f).fillMaxWidth().background(Color.Black)) {
            AndroidView(
                factory = { context ->
                    SurfaceView(context).apply {
                        holder.addCallback(
                            object : SurfaceHolder.Callback {
                                override fun surfaceCreated(holder: SurfaceHolder) {
                                    core.connect(target, holder.surface) { next -> post { state = next } }
                                }

                                override fun surfaceChanged(
                                    holder: SurfaceHolder,
                                    format: Int,
                                    width: Int,
                                    height: Int,
                                ) = Unit

                                override fun surfaceDestroyed(holder: SurfaceHolder) = core.disconnect()
                            },
                        )
                    }
                },
                modifier = Modifier.fillMaxSize(),
            )
            Box(
                modifier = Modifier.matchParentSize().pointerInput(core) {
                    awaitEachGesture {
                        val down = awaitFirstDown()
                        core.pointer(down.position.x.toInt(), down.position.y.toInt(), true)
                        do {
                            val change = awaitPointerEvent().changes.first()
                            core.pointer(change.position.x.toInt(), change.position.y.toInt(), change.pressed)
                        } while (change.pressed)
                    }
                },
            )
            when (val current = state) {
                RemoteDesktopState.Connecting -> StatusDot(DotTone.SPIN, Modifier.align(Alignment.Center))

                RemoteDesktopState.Showing -> Unit

                is RemoteDesktopState.Stopped -> BasicText(
                    words.refusal(current.refusal.code, current.refusal.wordParams),
                    modifier = Modifier.align(Alignment.Center).padding(24.dp),
                    style = NeutrinoTheme.note.copy(color = palette.textMuted, textAlign = TextAlign.Center),
                )
            }
            BasicTextField(
                value = "",
                onValueChange = { typed -> if (typed.isNotEmpty()) core.type(typed) },
                modifier = Modifier.size(1.dp).alpha(0f).focusRequester(focus),
            )
        }
    }
}
