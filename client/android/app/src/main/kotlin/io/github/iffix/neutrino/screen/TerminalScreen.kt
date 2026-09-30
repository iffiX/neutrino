package io.github.iffix.neutrino.screen

import android.content.ClipboardManager
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.iffix.neutrino.TERMINAL_KEY_CTRL
import io.github.iffix.neutrino.TERMINAL_KEY_PASTE
import io.github.iffix.neutrino.channel.ChannelTerminal
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.design.AppIcon
import io.github.iffix.neutrino.design.ButtonTier
import io.github.iffix.neutrino.design.DotTone
import io.github.iffix.neutrino.design.IconGlyph
import io.github.iffix.neutrino.design.NeutrinoButton
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.design.PlaceholderFrame
import io.github.iffix.neutrino.design.StatusDot
import io.github.iffix.neutrino.design.ToggleSwitch
import io.github.iffix.neutrino.terminal.TerminalPhase
import io.github.iffix.neutrino.terminal.TerminalTab
import io.github.iffix.neutrino.terminal.TerminalTabs
import io.github.iffix.neutrino.terminal.TerminalView

/**
 * The terminals, after the desktop client's window: the machines as chips with New terminal,
 * then the tab strip, the terminal, its persistent switch, and a row of the keys a phone lacks.
 *
 * @param hubs Every hub joined.
 * @param tabs Every terminal tab.
 * @param onJoin What pressing Join a hub does.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun TerminalScreen(hubs: List<HubView>, tabs: TerminalTabs, onJoin: () -> Unit) {
    val words = NeutrinoTheme.words
    val palette = NeutrinoTheme.palette
    val open by tabs.tabs.collectAsStateWithLifecycle()
    var active by remember { mutableStateOf(open.firstOrNull()?.sessionId.orEmpty()) }
    var pick by remember { mutableStateOf<Pair<HubView, ChannelTerminal>?>(null) }
    var ending by remember { mutableStateOf("") }
    var isCtrl by remember { mutableStateOf(false) }
    if (hubs.isEmpty()) {
        Column(modifier = Modifier.padding(16.dp)) { ServicesWaitFrame(onJoin) }
        return
    }
    if (open.none { it.sessionId == active }) active = open.lastOrNull()?.sessionId.orEmpty()
    val machines = hubs.filter { it.isConnected }.flatMap { hub -> hub.terminals.map { hub to it } }
    val picked = pick?.takeIf { chosen ->
        machines.any {
            it.first.binding.id == chosen.first.binding.id &&
                it.second == chosen.second
        }
    }
    val context = LocalContext.current
    Column(modifier = Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        if (machines.isEmpty()) {
            BasicText(words.word("ui.empty_terminals"), style = NeutrinoTheme.note)
        } else {
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                for ((hub, machine) in machines) {
                    MachineChip(
                        machine,
                        isOn = picked?.second == machine && picked.first.binding.id == hub.binding.id,
                    ) {
                        pick = hub to machine
                    }
                }
            }
            if (picked != null) {
                BasicText(
                    words.word(
                        "ui.machine_provided_by",
                        mapOf(
                            "hub" to picked.first.binding.title,
                            "device" to picked.second.name,
                        ),
                    ),
                    style = NeutrinoTheme.note,
                )
            }
            NeutrinoButton(
                words.word("ui.terminal_new"),
                {
                    val chosen = picked ?: return@NeutrinoButton
                    active = tabs.create(chosen.first.binding.id, chosen.second.deviceId, chosen.second.name)
                },
                tier = ButtonTier.PRIMARY,
                icon = AppIcon.TERMINAL,
                isWide = true,
                isEnabled = picked != null && picked.second.isOnline,
            )
        }
        if (open.isEmpty()) {
            PlaceholderFrame(line = words.word("ui.terminal_none"), hint = words.word("ui.terminal_pick_hint"))
            return@Column
        }
        val shape = RoundedCornerShape(12.dp)
        Column(
            modifier = Modifier
                .weight(1f)
                .clip(shape)
                .background(palette.surface)
                .border(1.dp, palette.border, shape),
        ) {
            TabStrip(open, active, onPick = { active = it }) { tab ->
                if (tab.isPersistent) ending = tab.sessionId else tabs.close(tab.sessionId)
            }
            open.firstOrNull { it.sessionId == ending }?.let { tab ->
                EndConfirm(tab, onEnd = {
                    tabs.close(tab.sessionId)
                    ending = ""
                }) { ending = "" }
            }
            Box(
                modifier = Modifier
                    .weight(1f)
                    .heightIn(min = 140.dp)
                    .padding(8.dp)
                    .clip(RoundedCornerShape(6.dp))
                    .background(palette.termBg),
            ) {
                TerminalPane(tabs, open.map { it.sessionId }.toSet(), active, isCtrl, onCtrlUsed = { isCtrl = false })
            }
            val tab = open.firstOrNull { it.sessionId == active }
            val isHubUp = tab != null && hubs.any { it.binding.id == tab.bindingId && it.isConnected }
            LaunchedEffect(active, tab?.phase, isHubUp) {
                if (isHubUp && tab.phase == TerminalPhase.DETACHED) tabs.reattach(active)
            }
            StatusLine(tab) { tabs.setPersistent(it.sessionId, !it.isPersistent) }
            ExtraKeys(isCtrl, onCtrl = { isCtrl = !isCtrl }) { key ->
                val bytes = if (key == TERMINAL_KEY_PASTE) {
                    context.getSystemService(ClipboardManager::class.java).primaryClip
                        ?.getItemAt(0)?.coerceToText(context)?.toString().orEmpty().toByteArray()
                } else {
                    key.toByteArray()
                }
                if (bytes.isNotEmpty() && active.isNotEmpty()) tabs.input(active, bytes)
            }
        }
    }
}

@Composable
private fun MachineChip(machine: ChannelTerminal, isOn: Boolean, onPick: () -> Unit) {
    val palette = NeutrinoTheme.palette
    val shape = RoundedCornerShape(50)
    Row(
        modifier = Modifier
            .clip(shape)
            .border(1.dp, if (isOn) palette.ok.copy(alpha = 0.6f) else palette.border, shape)
            .clickable(role = Role.RadioButton, onClick = onPick)
            .padding(horizontal = 12.dp, vertical = 6.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        StatusDot(if (machine.isOnline) DotTone.OK else DotTone.OFF)
        BasicText(machine.name, style = NeutrinoTheme.note.copy(color = if (isOn) palette.ok else palette.text))
    }
}

@Composable
private fun TabStrip(
    open: List<TerminalTab>,
    active: String,
    onPick: (String) -> Unit,
    onClose: (TerminalTab) -> Unit,
) {
    val palette = NeutrinoTheme.palette
    val words = NeutrinoTheme.words
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .horizontalScroll(rememberScrollState())
            .drawBehind {
                drawLine(palette.border, Offset(0f, size.height), Offset(size.width, size.height), 1.dp.toPx())
            }
            .padding(horizontal = 8.dp, vertical = 6.dp),
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        for ((index, tab) in open.withIndex()) {
            val isOn = tab.sessionId == active
            val name = "${tab.name} · ${index + 1}"
            val shape = RoundedCornerShape(6.dp)
            Row(
                modifier = Modifier
                    .clip(shape)
                    .background(if (isOn) palette.bg else palette.surface)
                    .border(1.dp, if (isOn) palette.border else palette.surface, shape),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                BasicText(
                    name,
                    style = NeutrinoTheme.mono.copy(color = if (isOn) palette.accent else palette.textMuted),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier
                        .clickable(role = Role.Tab) { onPick(tab.sessionId) }
                        .padding(start = 10.dp, end = 4.dp, top = 5.dp, bottom = 5.dp),
                )
                val label = words.word("ui.terminal_close", mapOf("name" to name))
                Box(
                    modifier = Modifier
                        .semantics { contentDescription = label }
                        .clickable(role = Role.Button) { onClose(tab) }
                        .padding(start = 4.dp, end = 8.dp, top = 5.dp, bottom = 5.dp),
                ) {
                    IconGlyph(AppIcon.CLOSE, palette.textMuted, size = 12.dp)
                }
            }
        }
    }
}

@Composable
private fun EndConfirm(tab: TerminalTab, onEnd: () -> Unit, onKeep: () -> Unit) {
    val palette = NeutrinoTheme.palette
    val words = NeutrinoTheme.words
    val shape = RoundedCornerShape(10.dp)
    Column(
        modifier = Modifier
            .padding(8.dp)
            .fillMaxWidth()
            .clip(shape)
            .background(palette.errorWash)
            .border(1.dp, palette.error, shape)
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        BasicText(words.word("ui.terminal_end_confirm", mapOf("name" to tab.name)), style = NeutrinoTheme.body)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            NeutrinoButton(words.word("ui.terminal_end"), onEnd, tier = ButtonTier.DANGER, isSmall = true)
            NeutrinoButton(words.word("ui.cancel"), onKeep, tier = ButtonTier.GHOST, isSmall = true)
        }
    }
}

@Composable
private fun TerminalPane(
    tabs: TerminalTabs,
    live: Set<String>,
    active: String,
    isCtrl: Boolean,
    onCtrlUsed: () -> Unit,
) {
    val palette = NeutrinoTheme.palette
    val context = LocalContext.current
    val view = remember { TerminalView(context, tabs, onCtrlUsed) }
    DisposableEffect(view) { onDispose { view.detach() } }
    LaunchedEffect(palette) { view.palette(palette) }
    LaunchedEffect(live) { view.panes(live) }
    LaunchedEffect(active, live) { view.show(active) }
    LaunchedEffect(isCtrl) { view.ctrl(isCtrl) }
    AndroidView(factory = { view }, modifier = Modifier.fillMaxSize())
}

@Composable
private fun StatusLine(tab: TerminalTab?, onPersist: (TerminalTab) -> Unit) {
    val words = NeutrinoTheme.words
    val palette = NeutrinoTheme.palette
    val note = tab?.note
    val line = when {
        tab == null -> ""
        note != null -> words.refusal(note.code, note.wordParams)
        tab.phase == TerminalPhase.ENDED -> words.word("ui.terminal_ended")
        tab.phase == TerminalPhase.DETACHED -> words.word("ui.terminal_detached")
        else -> words.word("ui.terminal_keys")
    }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .drawBehind { drawLine(palette.border, Offset.Zero, Offset(size.width, 0f), 1.dp.toPx()) }
            .padding(horizontal = 12.dp, vertical = 6.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        BasicText(
            line,
            style = NeutrinoTheme.mono.copy(color = if (note != null) palette.warn else palette.textMuted),
            modifier = Modifier.weight(1f),
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
        if (tab != null) {
            ToggleSwitch(
                words.word("ui.terminal_persistent"),
                isOn = tab.isPersistent,
                onChange = { onPersist(tab) },
                isEnabled = tab.phase == TerminalPhase.OPEN,
            )
        }
    }
}

@Composable
private fun ExtraKeys(isCtrl: Boolean, onCtrl: () -> Unit, onKey: (String) -> Unit) {
    val palette = NeutrinoTheme.palette
    val words = NeutrinoTheme.words
    val keys = listOf(
        "Esc" to "\u001b",
        "Tab" to "\t",
        "Ctrl" to TERMINAL_KEY_CTRL,
        "←" to "\u001b[D",
        "↑" to "\u001b[A",
        "↓" to "\u001b[B",
        "→" to "\u001b[C",
        words.word("ui.paste") to TERMINAL_KEY_PASTE,
    )
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(palette.elevated)
            .horizontalScroll(rememberScrollState())
            .padding(8.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        for ((label, key) in keys) {
            val isHeld = key == TERMINAL_KEY_CTRL && isCtrl
            val shape = RoundedCornerShape(6.dp)
            Box(
                modifier = Modifier
                    .heightIn(min = 34.dp)
                    .clip(shape)
                    .background(if (isHeld) palette.accentWash else palette.surface)
                    .border(1.dp, if (isHeld) palette.accent else palette.borderStrong, shape)
                    .clickable(role = Role.Button) { if (key == TERMINAL_KEY_CTRL) onCtrl() else onKey(key) }
                    .padding(horizontal = 12.dp, vertical = 7.dp),
                contentAlignment = Alignment.Center,
            ) {
                BasicText(label, style = NeutrinoTheme.mono.copy(color = if (isHeld) palette.accent else palette.text))
            }
        }
    }
}
