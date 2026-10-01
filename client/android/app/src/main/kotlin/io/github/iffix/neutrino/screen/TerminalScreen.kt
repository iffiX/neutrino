package io.github.iffix.neutrino.screen

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.isImeVisible
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.foundation.verticalScroll
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
import io.github.iffix.neutrino.CLIENT_TERMINAL_SHORT_HEIGHT_DP
import io.github.iffix.neutrino.TERMINAL_KEY_CTRL
import io.github.iffix.neutrino.channel.ChannelTerminal
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.design.AppIcon
import io.github.iffix.neutrino.design.Badge
import io.github.iffix.neutrino.design.ButtonTier
import io.github.iffix.neutrino.design.DotTone
import io.github.iffix.neutrino.design.ErrorLine
import io.github.iffix.neutrino.design.IconGlyph
import io.github.iffix.neutrino.design.LocalArm
import io.github.iffix.neutrino.design.NeutrinoButton
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.design.ReasonLine
import io.github.iffix.neutrino.design.StatusDot
import io.github.iffix.neutrino.design.SurfaceCard
import io.github.iffix.neutrino.design.ToggleSwitch
import io.github.iffix.neutrino.terminal.TerminalPhase
import io.github.iffix.neutrino.terminal.TerminalTab
import io.github.iffix.neutrino.terminal.TerminalTabs
import io.github.iffix.neutrino.terminal.TerminalView

/**
 * The terminals: a card of machine chips with New terminal, the tab strip, the terminal, the
 * status line with the two switches, and the key row. With the keyboard shown the chips and the
 * tabs collapse into one line, and the terminal takes the height left and refits.
 *
 * @param hubs Every hub joined.
 * @param tabs Every terminal tab.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun TerminalScreen(hubs: List<HubView>, tabs: TerminalTabs) {
    val words = NeutrinoTheme.words
    val palette = NeutrinoTheme.palette
    val open by tabs.tabs.collectAsStateWithLifecycle()
    val active by tabs.active.collectAsStateWithLifecycle()
    val pick by tabs.picked.collectAsStateWithLifecycle()
    var isCtrl by remember { mutableStateOf(false) }
    var isExpanded by remember { mutableStateOf(false) }
    val isKeyboard = WindowInsets.isImeVisible
    val machines = hubs.filter { it.isConnected }.flatMap { hub -> hub.terminals.map { hub to it } }
    val picked = machines.firstOrNull { (hub, machine) -> pick == hub.binding.id to machine.deviceId }
    val tab = open.firstOrNull { it.sessionId == active }
    BoxWithConstraints(modifier = Modifier.fillMaxSize().imePadding()) {
        val isShort = maxHeight < CLIENT_TERMINAL_SHORT_HEIGHT_DP.dp
        val isTight = isKeyboard || isShort
        LaunchedEffect(isTight) { if (!isTight) isExpanded = false }
        val isCollapsed = isTight && !isExpanded
        val isScrolled = isShort && isExpanded
        val terminalHeight = maxHeight
        Column(
            modifier = Modifier
                .fillMaxSize()
                .then(if (isScrolled) Modifier.verticalScroll(rememberScrollState()) else Modifier)
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            if (hubs.isEmpty()) {
                SurfaceCard { Sentence(words.word("ui.services_wait_join")) }
                return@Column
            }
            if (isCollapsed) {
                CollapsedLine(tab, open.indexOf(tab)) { isExpanded = true }
            } else {
                MachinesCard(
                    machines,
                    picked,
                    onPick = { hub, machine -> tabs.pick(hub.binding.id, machine.deviceId) },
                    onNew = { hub, machine -> tabs.create(hub.binding.id, machine.deviceId, machine.name) },
                )
            }
            if (open.isEmpty()) {
                SurfaceCard {
                    Sentence(words.word("ui.terminal_none"))
                    ReasonLine(words.word("ui.terminal_pick_hint"))
                }
                return@Column
            }
            val shape = RoundedCornerShape(12.dp)
            Column(
                modifier = Modifier
                    .then(if (isScrolled) Modifier.height(terminalHeight) else Modifier.weight(1f))
                    .clip(shape)
                    .background(palette.surface)
                    .border(1.dp, palette.border, shape),
            ) {
                if (!isCollapsed) TabStrip(open, active, onPick = tabs::select, onClose = tabs::close)
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .padding(8.dp)
                        .clip(RoundedCornerShape(6.dp))
                        .background(palette.termBg),
                ) {
                    TerminalPane(
                        tabs,
                        open.map { it.sessionId }.toSet(),
                        active,
                        isCtrl,
                        onCtrlUsed = { isCtrl = false },
                    )
                }
                val isHubUp = tab != null && hubs.any { it.binding.id == tab.bindingId && it.isConnected }
                LaunchedEffect(active, tab?.phase, isHubUp) {
                    if (isHubUp && tab.phase == TerminalPhase.DETACHED) tabs.reattach(active)
                }
                StatusLine(tab) { current, isPersistent, isShared ->
                    tabs.persist(current.sessionId, isPersistent, isShared)
                }
                KeyRow(isCtrl, onCtrl = { isCtrl = !isCtrl }) { key ->
                    if (active.isNotEmpty()) tabs.input(active, key.toByteArray())
                }
            }
        }
    }
}

@Composable
private fun Sentence(text: String) {
    BasicText(text, style = NeutrinoTheme.body, modifier = Modifier.padding(vertical = 12.dp))
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun MachinesCard(
    machines: List<Pair<HubView, ChannelTerminal>>,
    picked: Pair<HubView, ChannelTerminal>?,
    onPick: (HubView, ChannelTerminal) -> Unit,
    onNew: (HubView, ChannelTerminal) -> Unit,
) {
    val words = NeutrinoTheme.words
    SurfaceCard {
        Column(modifier = Modifier.padding(vertical = 12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (machines.isEmpty()) {
                BasicText(words.word("ui.empty_terminals"), style = NeutrinoTheme.body)
                return@Column
            }
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
                itemVerticalAlignment = Alignment.CenterVertically,
            ) {
                for ((hub, machine) in machines) {
                    MachineChip(machine, isOn = picked?.first == hub && picked.second == machine) {
                        onPick(hub, machine)
                    }
                }
                NeutrinoButton(
                    words.word("ui.terminal_new"),
                    { picked?.let { (hub, machine) -> onNew(hub, machine) } },
                    tier = ButtonTier.PRIMARY,
                    icon = AppIcon.TERMINAL,
                    isSmall = true,
                    isEnabled = picked != null && picked.second.isOnline,
                )
            }
            if (picked != null) {
                BasicText(
                    words.word(
                        "ui.machine_provided_by",
                        mapOf("hub" to picked.first.binding.title, "device" to picked.second.name),
                    ),
                    style = NeutrinoTheme.note,
                )
            }
            ReasonLine(
                when {
                    picked == null -> words.word("ui.reason.no_machine")
                    !picked.second.isOnline -> words.word("ui.reason.offline")
                    else -> null
                },
            )
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
private fun CollapsedLine(tab: TerminalTab?, index: Int, onExpand: () -> Unit) {
    val words = NeutrinoTheme.words
    val palette = NeutrinoTheme.palette
    val expand = words.word("ui.terminal_expand")
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .semantics { contentDescription = expand }
            .clickable(role = Role.Button, onClick = onExpand),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        BasicText(
            if (tab == null) "" else "${tab.name} · ${tabLabel(tab, index)}",
            style = NeutrinoTheme.mono.copy(color = palette.text),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f),
        )
        IconGlyph(AppIcon.CHEVRON_DOWN, palette.textMuted, size = 16.dp)
    }
}

@Composable
private fun tabLabel(tab: TerminalTab, index: Int): String = if (tab.phase ==
    TerminalPhase.ENDED
) {
    NeutrinoTheme.words.word("ui.terminal_ended")
} else {
    "${tab.name} · ${index + 1}"
}

@Composable
private fun TabStrip(open: List<TerminalTab>, active: String, onPick: (String) -> Unit, onClose: (String) -> Unit) {
    val palette = NeutrinoTheme.palette
    val words = NeutrinoTheme.words
    val arm = LocalArm.current
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
            val name = tabLabel(tab, index)
            val shape = RoundedCornerShape(6.dp)
            val armKey = "end-${tab.sessionId}"
            val isArmed = arm.armed == armKey
            Row(
                modifier = Modifier
                    .clip(shape)
                    .background(if (isOn) palette.bg else palette.surface)
                    .border(1.dp, if (isOn) palette.border else palette.surface, shape),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Row(
                    modifier = Modifier
                        .clickable(role = Role.Tab) { onPick(tab.sessionId) }
                        .padding(start = 10.dp, end = 4.dp, top = 5.dp, bottom = 5.dp),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    BasicText(
                        name,
                        style = NeutrinoTheme.mono.copy(color = if (isOn) palette.accent else palette.textMuted),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    if (tab.isPersistent) Badge(words.word("ui.badge.kept"))
                    if (tab.isShared) Badge(words.word("ui.badge.shared"))
                    if (tab.attachedCount > 1) Badge(tab.attachedCount.toString())
                }
                val label = words.word("ui.terminal_close", mapOf("name" to name))
                val isTwoPress = tab.isKept && tab.phase != TerminalPhase.ENDED
                Box(
                    modifier = Modifier
                        .semantics { contentDescription = label }
                        .clip(shape)
                        .background(if (isArmed) palette.error else palette.surface.copy(alpha = 0f))
                        .clickable(role = Role.Button) {
                            when {
                                !isTwoPress -> onClose(tab.sessionId)

                                isArmed -> {
                                    arm.armed = null
                                    onClose(tab.sessionId)
                                }

                                else -> arm.armed = armKey
                            }
                        }
                        .padding(start = 4.dp, end = 8.dp, top = 5.dp, bottom = 5.dp),
                ) {
                    if (isArmed) {
                        BasicText(
                            words.word("ui.terminal_end_armed"),
                            style = NeutrinoTheme.note.copy(color = palette.bg),
                        )
                    } else {
                        IconGlyph(AppIcon.CLOSE, palette.textMuted, size = 12.dp)
                    }
                }
            }
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
    val words = NeutrinoTheme.words
    val context = LocalContext.current
    val view = remember { TerminalView(context, tabs, onCtrlUsed) }
    DisposableEffect(view) { onDispose { view.detach() } }
    LaunchedEffect(palette) { view.palette(palette) }
    LaunchedEffect(words) {
        view.labels(
            copy = words.word("ui.menu.copy"),
            paste = words.word("ui.menu.paste"),
            selectAll = words.word("ui.menu.select_all"),
            clear = words.word("ui.menu.clear"),
        )
    }
    LaunchedEffect(live) { view.panes(live) }
    LaunchedEffect(active, live) { view.show(active) }
    LaunchedEffect(isCtrl) { view.ctrl(isCtrl) }
    AndroidView(factory = { view }, modifier = Modifier.fillMaxSize())
}

@Composable
private fun StatusLine(tab: TerminalTab?, onPersist: (TerminalTab, Boolean, Boolean) -> Unit) {
    val words = NeutrinoTheme.words
    val palette = NeutrinoTheme.palette
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .drawBehind { drawLine(palette.border, Offset.Zero, Offset(size.width, 0f), 1.dp.toPx()) }
            .padding(horizontal = 12.dp, vertical = 6.dp),
    ) {
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) {
            BasicText(
                when (tab?.phase) {
                    TerminalPhase.ENDED -> words.word("ui.terminal_ended")
                    TerminalPhase.DETACHED -> words.word("ui.terminal_detached")
                    else -> words.word("ui.terminal_keys")
                },
                style = NeutrinoTheme.mono.copy(color = palette.textMuted),
                modifier = Modifier.weight(1f),
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            if (tab != null) {
                ToggleSwitch(
                    words.word("ui.terminal_persistent"),
                    isOn = tab.isPersistent,
                    onChange = { onPersist(tab, it, tab.isShared) },
                    isEnabled = tab.canPersist,
                )
                ToggleSwitch(
                    words.word("ui.terminal_shared"),
                    isOn = tab.isShared,
                    onChange = { onPersist(tab, tab.isPersistent, it) },
                    isEnabled = tab.canPersist,
                )
            }
        }
        if (tab != null) {
            ErrorLine(tab.note)
            ReasonLine(
                words.word(
                    "ui.reason.not_owned",
                    mapOf(
                        "owner" to tab.ownerName.ifEmpty {
                            tab.owner
                        },
                    ),
                ).takeIf { !tab.isOwned },
            )
        }
    }
}

@Composable
private fun KeyRow(isCtrl: Boolean, onCtrl: () -> Unit, onKey: (String) -> Unit) {
    val palette = NeutrinoTheme.palette
    val keys = listOf(
        "Esc" to "\u001b",
        "Tab" to "\t",
        "Ctrl" to TERMINAL_KEY_CTRL,
        "←" to "\u001b[D",
        "↑" to "\u001b[A",
        "↓" to "\u001b[B",
        "→" to "\u001b[C",
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
