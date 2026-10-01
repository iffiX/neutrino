package io.github.iffix.neutrino.design

import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import io.github.iffix.neutrino.channel.ChannelResult

/**
 * A row's error line: the wording of the code its last action or its state ended in.
 *
 * @param refusal The code, or null for no line.
 */
@Composable
fun ErrorLine(refusal: ChannelResult.Refused?) {
    if (refusal == null) return
    BasicText(
        NeutrinoTheme.words.refusal(refusal.code, refusal.wordParams),
        style = NeutrinoTheme.note.copy(color = NeutrinoTheme.palette.warn),
    )
}

/**
 * A row's reason line: why one of its buttons is disabled, in one faint sentence.
 *
 * @param reason The sentence, or null for no line.
 */
@Composable
fun ReasonLine(reason: String?) {
    if (reason == null) return
    BasicText(reason, style = NeutrinoTheme.note.copy(color = NeutrinoTheme.palette.textFaint))
}
