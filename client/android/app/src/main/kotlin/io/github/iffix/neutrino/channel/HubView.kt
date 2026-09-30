package io.github.iffix.neutrino.channel

import io.github.iffix.neutrino.binding.HubBinding

/**
 * One hub as every screen reads it: the binding, where its socket stands, and what its last
 * state published.
 *
 * @property binding The binding as kept.
 * @property connection Where the socket stands.
 * @property software What the hub's welcome named, such as `neutrino_hub/0.5.0`.
 * @property isDisabled Whether the hub switched this client off.
 * @property lastError The last refusal or failure, null while all is well.
 * @property services The published list.
 * @property terminals The machines this phone may open a shell on.
 * @property connectedAddress The address the open socket runs on, empty while down.
 */
data class HubView(
    val binding: HubBinding,
    val connection: HubConnection = HubConnection.CONNECTING,
    val software: String = "",
    val isDisabled: Boolean = false,
    val lastError: ChannelResult.Refused? = null,
    val services: List<ChannelServiceEntry> = emptyList(),
    val terminals: List<ChannelTerminal> = emptyList(),
    val connectedAddress: String = "",
) {
    /** Whether the socket is open. */
    val isConnected: Boolean
        get() = connection == HubConnection.CONNECTED

    /**
     * The published entries of one type, empty while the hub has switched this client off.
     *
     * @param type `web`, `port`, `ai`, `file` or `rdp`.
     * @return The entries.
     */
    fun servicesOf(type: String): List<ChannelServiceEntry> =
        if (isDisabled) emptyList() else services.filter { it.type == type }
}
