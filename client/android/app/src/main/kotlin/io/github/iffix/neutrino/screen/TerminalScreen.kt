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
import androidx.compose.foundation.layout.Spacer
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
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.iffix.neutrino.CLIENT_TERMINAL_CARD_IME_MIN_HEIGHT_DP
import io.github.iffix.neutrino.CLIENT_TERMINAL_CARD_MIN_HEIGHT_DP
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
import io.github.iffix.neutrino.design.PageAction
import io.github.iffix.neutrino.design.ReasonLine
import io.github.iffix.neutrino.design.SelectedMark
import io.github.iffix.neutrino.design.StatusDot
import io.github.iffix.neutrino.design.SurfaceCard
import io.github.iffix.neutrino.design.ToggleSwitch
import io.github.iffix.neutrino.design.offerPageAction
import io.github.iffix.neutrino.terminal.TerminalKey
import io.github.iffix.neutrino.terminal.TerminalModifiers
import io.github.iffix.neutrino.terminal.TerminalPhase
import io.github.iffix.neutrino.terminal.TerminalTab
import io.github.iffix.neutrino.terminal.TerminalTabs
import io.github.iffix.neutrino.terminal.TerminalView

/**
 * The terminals: a card of machine chips with New terminal, then the terminal's card with the tab
 * strip, the terminal, the status line with the two switches and the key row, in one scrolling
 * column. Beside the sidebar New terminal is the header's action instead. The terminal's card is as
 * tall as the window under the top bar, the keyboard excluded, and never under its minimum, so one
 * screen holds it with its keys where the window allows and the page scrolls where it does not; nothing
 * collapses behind a tap. While the keyboard is shown the page stays scrolled to its end, so the key
 * row sits right above the keyboard and the terminal's last line right above the status line.
 *
 * @param hubs Every hub joined.
 * @param tabs Every terminal tab.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun TerminalScreen(hubs: List<HubView>, tabs: TerminalTabs) {
    val words = NeutrinoTheme.words
    val palette = NeutrinoTheme.palette
    val scroll = rememberScrollState()
    val isImeShown = WindowInsets.isImeVisible
    LaunchedEffect(isImeShown) {
        if (isImeShown) snapshotFlow { scroll.maxValue }.collect { scroll.scrollTo(it) }
    }
    val open by tabs.tabs.collectAsStateWithLifecycle()
    val active by tabs.active.collectAsStateWithLifecycle()
    val pick by tabs.picked.collectAsStateWithLifecycle()
    var modifiers by remember { mutableStateOf(TerminalModifiers()) }
    val machines = hubs.filter { it.isConnected }.flatMap { hub -> hub.terminals.map { hub to it } }
    val picked = machines.firstOrNull { (hub, machine) -> pick == hub.binding.id to machine.deviceId }
    val tab = open.firstOrNull { it.sessionId == active }
    val newTerminal = PageAction(
        words.word("ui.terminal_new"),
        AppIcon.TERMINAL,
        isEnabled = picked != null && picked.second.isOnline,
    ) { picked?.let { (hub, machine) -> tabs.create(hub.binding.id, machine.deviceId, machine.name) } }
    val isNewInHeader = offerPageAction(newTerminal)
    BoxWithConstraints(modifier = Modifier.fillMaxSize().imePadding()) {
        val cardHeight = terminalCardHeight(maxHeight, isImeShown)
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(scroll)
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            if (hubs.isEmpty()) {
                SurfaceCard { Sentence(words.word("ui.services_wait_join")) }
                return@Column
            }
            MachinesCard(
                machines,
                picked,
                onPick = { hub, machine -> tabs.pick(hub.binding.id, machine.deviceId) },
                newTerminal = newTerminal.takeUnless { isNewInHeader },
            )
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
                    .height(cardHeight)
                    .clip(shape)
                    .background(palette.surface)
                    .border(1.dp, palette.border, shape),
            ) {
                TabStrip(open, active, onPick = tabs::select, onClose = tabs::close)
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
                        modifiers,
                        onModifiersUsed = { modifiers = TerminalModifiers() },
                    )
                }
                val isHubUp = tab != null && hubs.any { it.binding.id == tab.bindingId && it.isConnected }
                LaunchedEffect(active, tab?.phase, isHubUp) {
                    if (isHubUp && tab.phase == TerminalPhase.DETACHED) tabs.reattach(active)
                }
                StatusLine(tab) { current, isPersistent, isShared ->
                    tabs.persist(current.sessionId, isPersistent, isShared)
                }
                KeyRow(modifiers) { key ->
                    if (key.isModifier) {
                        modifiers = modifiers.toggled(key)
                    } else {
                        if (active.isNotEmpty()) tabs.input(active, key.sequence(modifiers).toByteArray())
                        modifiers = TerminalModifiers()
                    }
                }
            }
        }
    }
}

/**
 * The height of the terminal's card: the window under the top bar less the page's gutters, and
 * never under its minimum, which is smaller while the keyboard is shown.
 *
 * @param windowHeight The page's height, the keyboard excluded.
 * @param isImeShown Whether the keyboard is shown.
 * @return The card's height.
 */
internal fun terminalCardHeight(windowHeight: Dp, isImeShown: Boolean): Dp {
    val least = if (isImeShown) CLIENT_TERMINAL_CARD_IME_MIN_HEIGHT_DP else CLIENT_TERMINAL_CARD_MIN_HEIGHT_DP
    return maxOf(windowHeight - 32.dp, least.dp)
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
    newTerminal: PageAction?,
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
                if (newTerminal != null) {
                    NeutrinoButton(
                        newTerminal.label,
                        newTerminal.onClick,
                        tier = ButtonTier.PRIMARY,
                        icon = newTerminal.icon,
                        isSmall = true,
                        isEnabled = newTerminal.isEnabled,
                    )
                }
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
            val mark = SelectedMark.of(palette, tab.sessionId == active)
            val name = tabLabel(tab, index)
            val shape = RoundedCornerShape(6.dp)
            val armKey = "end-${tab.sessionId}"
            val isArmed = arm.armed == armKey
            Row(
                modifier = Modifier
                    .clip(shape)
                    .background(mark.fill)
                    .border(1.dp, mark.border, shape),
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
                        style = NeutrinoTheme.mono.copy(color = mark.text),
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
                        .background(if (isArmed) palette.error else mark.fill)
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
    modifiers: TerminalModifiers,
    onModifiersUsed: () -> Unit,
) {
    val palette = NeutrinoTheme.palette
    val words = NeutrinoTheme.words
    val context = LocalContext.current
    val view = remember { TerminalView(context, tabs, onModifiersUsed) }
    DisposableEffect(view) { onDispose { view.detach() } }
    LaunchedEffect(palette) { view.palette(palette) }
    LaunchedEffect(words) {
        view.labels(
            copy = words.word("ui.menu.copy"),
            paste = words.word("ui.menu.paste"),
            selectAll = words.word("ui.menu.select_all"),
            clear = words.word("ui.menu.clear"),
            clearing = words.word("ui.job.clearing"),
        )
    }
    LaunchedEffect(live) { view.panes(live) }
    LaunchedEffect(active, live) { view.show(active) }
    LaunchedEffect(modifiers) { view.modifiers(modifiers) }
    val clearing by tabs.clearing.collectAsStateWithLifecycle()
    LaunchedEffect(clearing, live) { view.clearing(clearing) }
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
            val status =
                when (tab?.phase) {
                    TerminalPhase.ENDED -> words.word("ui.terminal_ended")
                    TerminalPhase.DETACHED -> words.word("ui.terminal_detached")
                    else -> null
                }
            if (status != null) {
                BasicText(
                    status,
                    style = NeutrinoTheme.mono.copy(color = palette.textMuted),
                    modifier = Modifier.weight(1f),
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            } else {
                Spacer(Modifier.weight(1f))
            }
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
            ReasonLine(words.word("ui.reason.not_owned", mapOf("owner" to tab.ownerLabel)).takeIf { !tab.isOwned })
        }
    }
}

@Composable
private fun KeyRow(modifiers: TerminalModifiers, onKey: (TerminalKey) -> Unit) {
    val palette = NeutrinoTheme.palette
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(palette.elevated)
            .horizontalScroll(rememberScrollState())
            .padding(8.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        for (key in TerminalKey.entries) {
            val isHeld = modifiers.isHeld(key)
            val shape = RoundedCornerShape(6.dp)
            Box(
                modifier = Modifier
                    .heightIn(min = 34.dp)
                    .clip(shape)
                    .background(if (isHeld) palette.accentWash else palette.surface)
                    .border(1.dp, if (isHeld) palette.accent else palette.borderStrong, shape)
                    .semantics { selected = isHeld }
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
    }
}
