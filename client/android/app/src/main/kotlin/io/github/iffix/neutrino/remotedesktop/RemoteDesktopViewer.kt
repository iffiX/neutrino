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
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.WindowInsetsSides
import androidx.compose.foundation.layout.displayCutout
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.only
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.AwaitPointerEventScope
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.PointerId
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.layout
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import io.github.iffix.neutrino.RDP_BARS_SHOWN_MILLIS
import io.github.iffix.neutrino.RDP_PINCH_SLOP_PX
import io.github.iffix.neutrino.RDP_TYPING_KEPT_CHARS
import io.github.iffix.neutrino.RDP_TYPING_SENTINEL
import io.github.iffix.neutrino.design.AppIcon
import io.github.iffix.neutrino.design.ButtonTier
import io.github.iffix.neutrino.design.DotTone
import io.github.iffix.neutrino.design.IconGlyph
import io.github.iffix.neutrino.design.NeutrinoButton
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.design.StatusDot
import kotlin.math.abs
import kotlin.math.roundToInt
import kotlinx.coroutines.delay

private enum class TouchStart { TAP, LONG_PRESS, DRAG, TWO_FINGERS }

private enum class TwoFingerMode { UNDECIDED, PINCH, SCROLL }

/**
 * The viewer over the whole screen, with the system's bars hidden until an edge swipe: the remote
 * picture under a bar with the machine's name, Keyboard and Disconnect, and a row of keys a phone
 * keyboard lacks with Paste beside them. Both bars hide [RDP_BARS_SHOWN_MILLIS] after the last
 * touch on them; a round handle at the top right shows or hides them. The keyboard covers the
 * picture's lower part without shrinking it, and the key bar sits right above the keyboard. A tap
 * clicks, a long press right-clicks, one finger drags, a pinch zooms and moves the picture, two
 * fingers scroll. Text copied on the remote machine lands on the phone's clipboard; Paste puts the
 * phone's clipboard on the remote machine's and presses Ctrl+V there.
 *
 * @param target The desktop to show.
 * @param core What decodes the picture and sends the input.
 * @param onCopied What text copied on the remote machine does: it goes on the phone's clipboard.
 * @param onClose What Disconnect and Back do.
 */
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
    var typing by remember {
        mutableStateOf(TextFieldValue(RDP_TYPING_SENTINEL, TextRange(RDP_TYPING_SENTINEL.length)))
    }
    val focus = remember { FocusRequester() }
    val context = LocalContext.current
    val copied = rememberUpdatedState(onCopied)
    val keyboard = LocalSoftwareKeyboardController.current
    val isShowing = state == RemoteDesktopState.Showing
    var isBarShown by remember { mutableStateOf(true) }
    var barTouches by remember { mutableIntStateOf(0) }
    val view = LocalView.current
    val keyboardHeight = WindowInsets.ime.getBottom(LocalDensity.current)
    BackHandler(onBack = onClose)
    DisposableEffect(view) {
        val bars = view.context.findActivity()?.window?.let { WindowCompat.getInsetsController(it, view) }
        bars?.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        bars?.hide(WindowInsetsCompat.Type.systemBars())
        onDispose { bars?.show(WindowInsetsCompat.Type.systemBars()) }
    }
    LaunchedEffect(isBarShown, barTouches) {
        if (isBarShown) {
            delay(RDP_BARS_SHOWN_MILLIS)
            isBarShown = false
        }
    }
    LaunchedEffect(keyboardHeight) { viewport = viewport.coveredBy(keyboardHeight.toFloat()) }
    val onBarTouch = Modifier.pointerInput(Unit) {
        awaitEachGesture {
            awaitFirstDown(requireUnconsumed = false, pass = PointerEventPass.Initial)
            barTouches += 1
        }
    }
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
    val releaseHeld = {
        for (key in held) core.key(key.code, false)
        held = emptySet()
    }
    val pressKey = { code: String ->
        core.key(code, true)
        core.key(code, false)
        releaseHeld()
    }
    val onBarKey = { key: RemoteDesktopKey ->
        when {
            !key.isModifier -> pressKey(key.code)

            key in held -> {
                core.key(key.code, false)
                held = held - key
            }

            else -> {
                core.key(key.code, true)
                held = held + key
            }
        }
    }
    val onTyped = { text: String ->
        val code = text.singleOrNull()?.let { RemoteDesktopKey.codeOf(it) }
        when {
            text == "\n" -> pressKey(RemoteDesktopKey.ENTER)

            held.isNotEmpty() && code != null -> pressKey(code)

            else -> {
                core.type(text)
                releaseHeld()
            }
        }
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
            BasicTextField(
                value = typing,
                onValueChange = { next ->
                    val edit = RemoteDesktopTyping.between(typing.text, next.text)
                    repeat(edit.backspaces) { pressKey(RemoteDesktopKey.BACKSPACE) }
                    if (edit.text.isNotEmpty()) onTyped(edit.text)
                    val isSettled = next.composition == null &&
                        (next.text.isEmpty() || next.text.length > RDP_TYPING_KEPT_CHARS)
                    typing = if (isSettled) {
                        TextFieldValue(RDP_TYPING_SENTINEL, TextRange(RDP_TYPING_SENTINEL.length))
                    } else {
                        next
                    }
                },
                keyboardOptions = KeyboardOptions(autoCorrectEnabled = false, keyboardType = KeyboardType.Ascii),
                modifier = Modifier.size(1.dp).alpha(0f).focusRequester(focus),
            )
        }
        if (isBarShown) {
            Row(
                modifier = Modifier
                    .align(Alignment.TopCenter)
                    .fillMaxWidth()
                    .then(onBarTouch)
                    .background(palette.bg)
                    .windowInsetsPadding(edges)
                    .padding(start = 12.dp, end = 60.dp, top = 8.dp, bottom = 8.dp),
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
                    isEnabled = isShowing,
                    isSmall = true,
                )
                NeutrinoButton(
                    label = words.word("ui.rdp_disconnect"),
                    onClick = onClose,
                    tier = ButtonTier.DANGER,
                    isSmall = true,
                )
            }
        }
        BarHandle(
            isBarShown,
            onPress = {
                isBarShown = !isBarShown
                barTouches += 1
            },
            modifier = Modifier.align(Alignment.TopEnd).windowInsetsPadding(edges).padding(top = 6.dp, end = 12.dp),
        )
        if (isShowing && isBarShown) {
            KeyBar(held, onBarKey, modifier = Modifier.align(Alignment.BottomCenter).imePadding().then(onBarTouch)) {
                val text = context.getSystemService(ClipboardManager::class.java).primaryClip
                    ?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.coerceToText(context)?.toString().orEmpty()
                if (text.isNotEmpty()) {
                    core.clipboard(text)
                    core.key(RemoteDesktopKey.CTRL.code, true)
                    core.key(RemoteDesktopKey.PASTE, true)
                    core.key(RemoteDesktopKey.PASTE, false)
                    core.key(RemoteDesktopKey.CTRL.code, false)
                    releaseHeld()
                }
            }
        }
    }
}

@Composable
private fun BarHandle(isBarShown: Boolean, onPress: () -> Unit, modifier: Modifier = Modifier) {
    val palette = NeutrinoTheme.palette
    val label = NeutrinoTheme.words.word(if (isBarShown) "ui.rdp_bars_hide" else "ui.rdp_bars_show")
    Box(
        modifier = modifier
            .size(36.dp)
            .clip(CircleShape)
            .background(palette.surface.copy(alpha = 0.6f))
            .border(1.dp, palette.borderStrong.copy(alpha = 0.6f), CircleShape)
            .semantics { contentDescription = label }
            .clickable(role = Role.Button, onClick = onPress),
        contentAlignment = Alignment.Center,
    ) {
        IconGlyph(if (isBarShown) AppIcon.CHEVRON_UP else AppIcon.CHEVRON_DOWN, palette.text, size = 18.dp)
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
