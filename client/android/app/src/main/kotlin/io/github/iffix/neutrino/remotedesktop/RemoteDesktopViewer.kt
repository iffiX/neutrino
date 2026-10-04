package io.github.iffix.neutrino.remotedesktop

import android.app.Activity
import android.content.ClipboardManager
import android.content.Context
import android.content.ContextWrapper
import android.view.SurfaceHolder
import android.view.SurfaceView
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.WindowInsetsSides
import androidx.compose.foundation.layout.displayCutout
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.isImeVisible
import androidx.compose.foundation.layout.only
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.AwaitPointerEventScope
import androidx.compose.ui.input.pointer.PointerId
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.layout
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import io.github.iffix.neutrino.RDP_PINCH_SLOP_PX
import io.github.iffix.neutrino.design.DotTone
import io.github.iffix.neutrino.design.IconGlyph
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.design.StatusDot
import kotlin.math.abs
import kotlin.math.roundToInt

private enum class TouchStart { TAP, LONG_PRESS, DRAG, TWO_FINGERS }

private enum class TwoFingerMode { UNDECIDED, PINCH, SCROLL }

/**
 * The viewer over the whole screen, with the system's bars hidden until an edge swipe: the remote
 * picture, and three round buttons at the top right that always stay. Keyboard raises or puts
 * away the phone's keyboard, Keys shows or hides a row of keys a phone keyboard lacks with Paste
 * beside them, Close ends the session; the keyboard and the key bar start off. The keyboard covers
 * the picture's lower part without shrinking it, and the key bar sits at the bottom edge, right
 * above the keyboard while it is up. A tap clicks, a long press right-clicks, one finger drags, a
 * pinch zooms and moves the picture, two fingers scroll. Text copied on the remote machine lands
 * on the phone's clipboard; Paste puts the phone's clipboard on the remote machine's and presses
 * Ctrl+V there.
 *
 * @param target The desktop to show.
 * @param core What decodes the picture and sends the input.
 * @param onCopied What text copied on the remote machine does: it goes on the phone's clipboard.
 * @param onClose What Close and Back do.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun RemoteDesktopViewer(
    target: RemoteDesktopTarget,
    core: RemoteDesktopCore,
    onCopied: (String) -> Unit,
    onClose: () -> Unit,
) {
    val words = NeutrinoTheme.words
    val palette = NeutrinoTheme.palette
    var state by remember(target) { mutableStateOf<RemoteDesktopState>(RemoteDesktopState.Connecting) }
    var viewport by remember(target) { mutableStateOf(RemoteDesktopViewport()) }
    var held by remember(target) { mutableStateOf(emptySet<RemoteDesktopKey>()) }
    val scope = rememberCoroutineScope()
    val sender = remember(target, core) {
        RemoteDesktopInputSender(core, target.platformOs, scope) { keys -> held = keys }
    }
    val context = LocalContext.current
    val input = remember(sender) { RemoteDesktopInputView(context).apply { this.sender = sender } }
    val copied = rememberUpdatedState(onCopied)
    val isShowing = state == RemoteDesktopState.Showing
    var isKeyBarShown by remember { mutableStateOf(false) }
    val view = LocalView.current
    val keyboard = RemoteDesktopKeyboard(WindowInsets.isImeVisible, WindowInsets.ime.getBottom(LocalDensity.current))
    BackHandler(onBack = onClose)
    DisposableEffect(view) {
        val bars = view.context.findActivity()?.window?.let { WindowCompat.getInsetsController(it, view) }
        bars?.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        bars?.hide(WindowInsetsCompat.Type.systemBars())
        onDispose { bars?.show(WindowInsetsCompat.Type.systemBars()) }
    }
    DisposableEffect(input) { onDispose { input.hideKeyboard() } }
    DisposableEffect(sender) { onDispose { sender.close() } }
    LaunchedEffect(keyboard.height) { viewport = viewport.coveredBy(keyboard.height.toFloat()) }
    LaunchedEffect(keyboard.isFocusKept) { if (!keyboard.isFocusKept) input.releaseFocus() }
    SideEffect { input.holdFocus() }
    DisposableEffect(target, core) {
        core.connect(
            target,
            onState = { next -> state = next },
            onFrameSize = { width, height ->
                viewport = viewport.sized(viewport.viewWidth, viewport.viewHeight, width, height)
            },
            onClipboard = { text -> copied.value(text) },
        )
        onDispose { core.disconnect() }
    }
    val edges = WindowInsets.displayCutout.only(WindowInsetsSides.Top + WindowInsetsSides.Horizontal)
    Box(modifier = Modifier.fillMaxSize().background(Color.Black)) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .clipToBounds()
                .onSizeChanged { size ->
                    viewport = viewport.sized(
                        size.width.toFloat(),
                        size.height.toFloat(),
                        viewport.frameWidth,
                        viewport.frameHeight,
                    )
                },
        ) {
            AndroidView(
                factory = { context ->
                    SurfaceView(context).apply {
                        holder.addCallback(
                            object : SurfaceHolder.Callback {
                                override fun surfaceCreated(holder: SurfaceHolder) = core.attach(holder.surface)

                                override fun surfaceChanged(
                                    holder: SurfaceHolder,
                                    format: Int,
                                    width: Int,
                                    height: Int,
                                ) = Unit

                                override fun surfaceDestroyed(holder: SurfaceHolder) = core.attach(null)
                            },
                        )
                    }
                },
                modifier = Modifier.layout { measurable, constraints ->
                    val width = viewport.drawnWidth.roundToInt().coerceAtLeast(1)
                    val height = viewport.drawnHeight.roundToInt().coerceAtLeast(1)
                    val placeable = measurable.measure(Constraints.fixed(width, height))
                    layout(constraints.maxWidth, constraints.maxHeight) {
                        placeable.place(viewport.left.roundToInt(), viewport.top.roundToInt())
                    }
                },
            )
            Box(
                modifier = Modifier.matchParentSize().pointerInput(core, isShowing) {
                    if (!isShowing) return@pointerInput
                    awaitEachGesture {
                        val first = awaitFirstDown()
                        val start = withTimeoutOrNull(viewConfiguration.longPressTimeoutMillis) {
                            touchStart(first.id, first.position, viewConfiguration.touchSlop)
                        } ?: TouchStart.LONG_PRESS
                        val (x, y) = viewport.toFrame(first.position.x, first.position.y)
                        when (start) {
                            TouchStart.TAP -> RemoteDesktopMouse.tap(x, y).forEach(core::mouse)

                            TouchStart.LONG_PRESS -> {
                                RemoteDesktopMouse.longPress(x, y).forEach(core::mouse)
                                awaitAllUp()
                            }

                            TouchStart.DRAG -> {
                                RemoteDesktopMouse.dragStart(x, y).forEach(core::mouse)
                                var last = first.position
                                while (true) {
                                    val change = awaitPointerEvent().changes.firstOrNull { it.id == first.id } ?: break
                                    last = change.position
                                    val (dragX, dragY) = viewport.toFrame(last.x, last.y)
                                    if (!change.pressed) break
                                    core.mouse(RemoteDesktopMouse.dragMove(dragX, dragY))
                                }
                                val (endX, endY) = viewport.toFrame(last.x, last.y)
                                core.mouse(RemoteDesktopMouse.dragEnd(endX, endY))
                                awaitAllUp()
                            }

                            TouchStart.TWO_FINGERS -> {
                                twoFingers(
                                    onPinch = { factor, focusX, focusY, dx, dy ->
                                        viewport = viewport.zoomedBy(factor, focusX, focusY).pannedBy(dx, dy)
                                    },
                                    onScroll = core::mouse,
                                )
                                awaitAllUp()
                            }
                        }
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
        }
        key(input) { AndroidView(factory = { input }, modifier = Modifier.size(1.dp)) }
        Row(
            modifier = Modifier.align(Alignment.TopEnd).windowInsetsPadding(edges).padding(top = 6.dp, end = 12.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            for (button in RemoteDesktopButton.entries) {
                RoundButton(
                    button,
                    isActive = button.isActive(keyboard, isKeyBarShown),
                    isEnabled = isShowing || button == RemoteDesktopButton.CLOSE,
                ) {
                    button.press(
                        keyboard,
                        isKeyBarShown,
                        onKeyboard = { isUp -> if (isUp) input.showKeyboard() else input.hideKeyboard() },
                        onKeyBar = { isShown -> isKeyBarShown = isShown },
                        onClose = onClose,
                    )
                }
            }
        }
        if (isShowing && isKeyBarShown) {
            KeyBar(held, sender::barKey, modifier = Modifier.align(Alignment.BottomCenter).imePadding()) {
                sender.paste(
                    context.getSystemService(ClipboardManager::class.java).primaryClip
                        ?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.coerceToText(context)?.toString().orEmpty(),
                )
            }
        }
    }
}

@Composable
private fun RoundButton(button: RemoteDesktopButton, isActive: Boolean, isEnabled: Boolean, onPress: () -> Unit) {
    val palette = NeutrinoTheme.palette
    val label = NeutrinoTheme.words.word(button.wordKey)
    val tone = when {
        button.isDanger -> palette.error
        isActive -> palette.accent
        else -> palette.text
    }
    Box(
        modifier = Modifier
            .size(36.dp)
            .alpha(if (isEnabled) 1f else 0.4f)
            .clip(CircleShape)
            .background(palette.surface.copy(alpha = 0.6f))
            .background(if (isActive) palette.accentWash else Color.Transparent)
            .border(
                1.dp,
                if (isActive ||
                    button.isDanger
                ) {
                    tone
                } else {
                    palette.borderStrong.copy(alpha = 0.6f)
                },
                CircleShape,
            )
            .semantics { contentDescription = label }
            .clickable(enabled = isEnabled, role = Role.Button, onClick = onPress),
        contentAlignment = Alignment.Center,
    ) {
        IconGlyph(button.icon, tone, size = 18.dp)
    }
}

@Composable
private fun KeyBar(
    held: Set<RemoteDesktopKey>,
    onKey: (RemoteDesktopKey) -> Unit,
    modifier: Modifier = Modifier,
    onPaste: () -> Unit,
) {
    val palette = NeutrinoTheme.palette
    val words = NeutrinoTheme.words
    Row(
        modifier = modifier
            .fillMaxWidth()
            .background(palette.elevated)
            .horizontalScroll(rememberScrollState())
            .padding(8.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        for (key in RemoteDesktopKey.entries) {
            val isHeld = key in held
            val shape = RoundedCornerShape(6.dp)
            Box(
                modifier = Modifier
                    .heightIn(min = 34.dp)
                    .clip(shape)
                    .background(if (isHeld) palette.accentWash else palette.surface)
                    .border(1.dp, if (isHeld) palette.accent else palette.borderStrong, shape)
                    .clickable(role = Role.Button) { onKey(key) }
                    .padding(horizontal = 12.dp, vertical = 7.dp),
                contentAlignment = Alignment.Center,
            ) {
                BasicText(
                    key.label,
                    style = NeutrinoTheme.mono.copy(color = if (isHeld) palette.accent else palette.text),
                )
            }
        }
        val shape = RoundedCornerShape(6.dp)
        Box(
            modifier = Modifier
                .heightIn(min = 34.dp)
                .clip(shape)
                .background(palette.surface)
                .border(1.dp, palette.borderStrong, shape)
                .clickable(role = Role.Button, onClick = onPaste)
                .padding(horizontal = 12.dp, vertical = 7.dp),
            contentAlignment = Alignment.Center,
        ) {
            BasicText(words.word("ui.paste"), style = NeutrinoTheme.mono.copy(color = palette.text))
        }
    }
}

private fun Context.findActivity(): Activity? = when (this) {
    is Activity -> this
    is ContextWrapper -> baseContext.findActivity()
    else -> null
}

private suspend fun AwaitPointerEventScope.touchStart(id: PointerId, origin: Offset, slop: Float): TouchStart {
    while (true) {
        val event = awaitPointerEvent()
        if (event.changes.count { it.pressed } >= 2) return TouchStart.TWO_FINGERS
        val change = event.changes.firstOrNull { it.id == id } ?: continue
        if (!change.pressed) return TouchStart.TAP
        if ((change.position - origin).getDistance() > slop) return TouchStart.DRAG
    }
}

private suspend fun AwaitPointerEventScope.twoFingers(
    onPinch: (factor: Float, focusX: Float, focusY: Float, dx: Float, dy: Float) -> Unit,
    onScroll: (RemoteDesktopMouse) -> Unit,
) {
    var mode = TwoFingerMode.UNDECIDED
    var origin: Pair<Offset, Float>? = null
    var previous: Pair<Offset, Float>? = null
    var travel = 0f
    while (true) {
        val pressed = awaitPointerEvent().changes.filter { it.pressed }
        if (pressed.size < 2) return
        val centre = (pressed[0].position + pressed[1].position) / 2f
        val spread = (pressed[0].position - pressed[1].position).getDistance()
        val before = previous ?: (centre to spread)
        val first = origin ?: (centre to spread).also { origin = it }
        previous = centre to spread
        if (mode == TwoFingerMode.UNDECIDED) {
            mode = when {
                abs(spread - first.second) > RDP_PINCH_SLOP_PX -> TwoFingerMode.PINCH
                (centre - first.first).getDistance() > RDP_PINCH_SLOP_PX -> TwoFingerMode.SCROLL
                else -> TwoFingerMode.UNDECIDED
            }
        }
        when (mode) {
            TwoFingerMode.PINCH -> {
                val factor = if (before.second > 0f) spread / before.second else 1f
                val move = centre - before.first
                onPinch(factor, centre.x, centre.y, move.x, move.y)
            }

            TwoFingerMode.SCROLL -> {
                val (wheel, rest) = RemoteDesktopMouse.wheel(travel + (centre.y - before.first.y))
                travel = rest
                wheel?.let(onScroll)
            }

            TwoFingerMode.UNDECIDED -> Unit
        }
    }
}

private suspend fun AwaitPointerEventScope.awaitAllUp() {
    do {
        val event = awaitPointerEvent()
    } while (event.changes.any { it.pressed })
}
