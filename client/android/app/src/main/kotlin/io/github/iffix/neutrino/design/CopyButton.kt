package io.github.iffix.neutrino.design

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import io.github.iffix.neutrino.CLIENT_COPIED_SHOWN_MILLIS
import kotlinx.coroutines.delay

/**
 * A copy button that confirms in place: green and `Copied` for a moment.
 *
 * @param isEnabled Whether it takes presses.
 * @param onCopy What copying does.
 */
@Composable
fun CopyButton(isEnabled: Boolean = true, onCopy: () -> Unit) {
    val words = NeutrinoTheme.words
    var isDone by remember { mutableStateOf(false) }
    LaunchedEffect(isDone) {
        if (isDone) {
            delay(CLIENT_COPIED_SHOWN_MILLIS)
            isDone = false
        }
    }
    NeutrinoButton(
        label = words.word(if (isDone) "ui.copied" else "ui.copy"),
        onClick = {
            onCopy()
            isDone = true
        },
        isSmall = true,
        isEnabled = isEnabled,
        isDone = isDone,
    )
}
