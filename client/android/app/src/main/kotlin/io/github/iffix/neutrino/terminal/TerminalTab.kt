package io.github.iffix.neutrino.terminal

import io.github.iffix.neutrino.CLIENT_REFUSAL_CODE_BINDING_UNKNOWN
import io.github.iffix.neutrino.CLIENT_REFUSAL_CODE_DISABLED
import io.github.iffix.neutrino.channel.ChannelResult

/**
 * One terminal tab: a shell session on a managed machine, opened here or listed by the hub.
 *
 * @property sessionId The shell's session id; also the tab's id.
 * @property bindingId The hub the machine is managed by.
 * @property deviceId The machine.
 * @property name The machine's name.
 * @property account The account the shell runs as, empty for the machine's first enabled one.
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
 * @property isOpening Whether the shell's stream is being opened.
 * @property hubEnd The hub's refusal the tab ended with, `client_disabled` or `binding_unknown`;
 *   empty for none.
 */
data class TerminalTab(
    val sessionId: String,
    val bindingId: String,
    val deviceId: String,
    val name: String,
    val account: String = "",
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
    val isOpening: Boolean = false,
    val hubEnd: String = "",
) {
    /** Whether closing the tab ends the session for everyone, which takes two presses. */
    val isKept: Boolean
        get() = isPersistent || isShared

    /** Whether the two switches act: the tab is open and this phone opened its session. */
    val canPersist: Boolean
        get() = phase == TerminalPhase.OPEN && isOwned

    /** The key of the words the status line shows for the tab; null while it is open or opening. */
    val statusKey: String?
        get() = when (phase) {
            TerminalPhase.ENDED -> when (hubEnd) {
                CLIENT_REFUSAL_CODE_DISABLED -> "ui.terminal.disabled"
                CLIENT_REFUSAL_CODE_BINDING_UNKNOWN -> "ui.terminal.unknown_device"
                else -> "ui.terminal_ended"
            }

            TerminalPhase.DETACHED -> "ui.terminal.detached"

            else -> null
        }

    /** Who opened the session, for the reason line of a tab this phone does not own: the name, else the stamp. */
    val ownerLabel: String
        get() = ownerName.ifEmpty { owner }
}
