package io.github.iffix.neutrino.screen

import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.toggleableState
import androidx.compose.ui.state.ToggleableState
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.design.DotTone
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.design.PickerField
import io.github.iffix.neutrino.design.StatusDot
import io.github.iffix.neutrino.overlay.OverlayPhase
import io.github.iffix.neutrino.overlay.OverlayStatus

/**
 * A hub row's virtual network: the chip that joins and leaves it (green on, amber joining or
 * leaving, grey off), and the picker between the hub's networks when it publishes more than one.
 *
 * @param hub The hub.
 * @param status What the running engine last said, for whichever hub it runs.
 * @param onToggle What pressing the chip does, with the wish it asks for.
 * @param onPick What choosing a network does, with its provider.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun OverlayChipLine(hub: HubView, status: OverlayStatus?, onToggle: (Boolean) -> Unit, onPick: (String) -> Unit) {
    val words = NeutrinoTheme.words
    val palette = NeutrinoTheme.palette
    val overlays = hub.binding.overlays
    if (overlays.isEmpty()) return
    val mine = status?.takeIf { it.bindingId == hub.binding.id }
    val phase = when {
        mine != null -> mine.phase
        hub.binding.isOverlayWanted -> OverlayPhase.JOINING
        else -> OverlayPhase.OFF
    }
    val chosen =
        overlays.firstOrNull { it.provider == (mine?.provider ?: hub.binding.overlayChoice) } ?: overlays.first()
    val isMoving = phase == OverlayPhase.JOINING || phase == OverlayPhase.LEAVING
    val color = when (phase) {
        OverlayPhase.ON -> palette.ok
        OverlayPhase.JOINING, OverlayPhase.LEAVING -> palette.warn
        else -> palette.text
    }
    val parts = when (phase) {
        OverlayPhase.ON -> listOf(words.word("ui.overlay_on"), chosen.title, mine?.address.orEmpty())
        OverlayPhase.JOINING -> listOf(words.word("ui.overlay_joining"), chosen.title)
        OverlayPhase.LEAVING -> listOf(words.word("ui.overlay_leaving"), chosen.title)
        OverlayPhase.FAILED -> listOf(words.word("ui.overlay_failed"), chosen.title)
        OverlayPhase.OFF -> listOf(words.word("ui.overlay"), words.word("ui.overlay_off"))
    }.filter { it.isNotEmpty() }
    val isOn = phase == OverlayPhase.ON || hub.binding.isOverlayWanted
    Column(modifier = Modifier.padding(top = 8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
            itemVerticalAlignment = Alignment.CenterVertically,
        ) {
            val shape = RoundedCornerShape(50)
            Row(
                modifier = Modifier
                    .clip(shape)
                    .border(
                        1.dp,
                        if (phase == OverlayPhase.ON ||
                            isMoving
                        ) {
                            color.copy(alpha = 0.6f)
                        } else {
                            palette.border
                        },
                        shape,
                    )
                    .semantics { toggleableState = if (isOn) ToggleableState.On else ToggleableState.Off }
                    .clickable(enabled = !isMoving, role = Role.Switch) { onToggle(!isOn) }
                    .padding(horizontal = 12.dp, vertical = 6.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                StatusDot(
                    when (phase) {
                        OverlayPhase.ON -> DotTone.OK
                        OverlayPhase.JOINING, OverlayPhase.LEAVING -> DotTone.SPIN
                        else -> DotTone.OFF
                    },
                )
                BasicText(
                    parts.joinToString(" · "),
                    style = NeutrinoTheme.note.copy(color = color),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            if (overlays.size > 1) {
                PickerField(
                    options = overlays.map { it.provider to it.title },
                    selected = chosen.provider,
                    onSelect = onPick,
                    head = words.word("ui.overlay_count", mapOf("count" to overlays.size)),
                    isEnabled = !isMoving,
                    isWide = false,
                )
            }
        }
        val refusal = mine?.refusal
        if (phase == OverlayPhase.FAILED && refusal != null) {
            BasicText(
                words.refusal(refusal.code, refusal.wordParams),
                style = NeutrinoTheme.note.copy(color = palette.warn),
            )
        }
    }
}

@Preview(widthDp = 400, heightDp = 200)
@Composable
private fun OverlayChipLinePreview() {
    PreviewHubs.Frame(mapOf("ui.overlay_on" to "已加入", "ui.overlay_count" to "此 hub 发布了 {count} 个虚拟网")) {
        OverlayChipLine(
            PreviewHubs.neutrino,
            OverlayStatus("b1", "netbird", OverlayPhase.ON, "100.72.4.9"),
            onToggle = {},
            onPick = {},
        )
    }
}
