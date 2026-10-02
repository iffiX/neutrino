package io.github.iffix.neutrino.terminal

import io.github.iffix.neutrino.channel.ChannelResult

/**
 * One terminal tab: a shell session on a managed machine, opened here or listed by the hub.
 *
 * @property sessionId The shell's session id; also the tab's id.
 * @property bindingId The hub the machine is managed by.
 * @property deviceId The machine.
 * @property name The machine's name.
 * @property title What the shell last set as its title.
 * @property owner Who opened the session, as the hub names it; empty until the hub lists it.
 * @property ownerName The opener's name, as the hub lists it; empty until the hub lists it.
 * @property isOwned Whether this phone opened the session.
 * @property isPersistent Whether the session outlives every window.
 * @property isShared Whether every client with terminal rights on the machine lists the session.
 * @property attachedCount How many windows show the session, as the last state frame says.
 * @property isListed Whether the hub has listed the session since the tab was made.
 * @property phase Where the tab's stream stands.
 * @property note Why the shell ended, the stream dropped or a command was refused.
 */
data class TerminalTab(
    val sessionId: String,
    val bindingId: String,
    val deviceId: String,
    val name: String,
    val title: String = "",
    val owner: String = "",
    val ownerName: String = "",
    val isOwned: Boolean = true,
    val isPersistent: Boolean = false,
    val isShared: Boolean = false,
    val attachedCount: Int = 0,
    val isListed: Boolean = false,
    val phase: TerminalPhase = TerminalPhase.DETACHED,
    val note: ChannelResult.Refused? = null,
) {
    /** Whether closing the tab ends the session for everyone, which takes two presses. */
    val isKept: Boolean
        get() = isPersistent || isShared

    /** Whether the two switches act: the tab is open and this phone opened its session. */
    val canPersist: Boolean
        get() = phase == TerminalPhase.OPEN && isOwned

    /** Who opened the session, for the reason line of a tab this phone does not own: the name, else the stamp. */
    val ownerLabel: String
        get() = ownerName.ifEmpty { owner }
}
