package io.github.iffix.neutrino.channel

import io.github.iffix.neutrino.binding.HubBinding
import io.github.iffix.neutrino.overlay.OverlayLine

/**
 * One hub as every screen reads it: the binding, where its socket stands, what its last state
 * published, its virtual network, and the jobs running on it.
 *
 * @property binding The binding as kept.
 * @property connection Where the socket stands.
 * @property software What the hub's welcome named, such as `neutrino_hub/0.5.0`.
 * @property lastError The code the last round or the open socket ended in, null while all is well.
 * @property services The published list.
 * @property terminals The machines this phone may open a shell on.
 * @property connectedAddress The address the open socket runs on, empty while down.
 * @property hasConnected Whether the hub welcomed this phone since the app started.
 * @property droppedAtMillis When the open socket last closed, in the session's clock; 0 while open or before the first.
 * @property jobs The actions running on the hub.
 * @property jobError The code of a leave whose binding could not be forgotten here, or of a failed Panel, kept
 *   until the next press on the row or a refresh.
 * @property overlay The hub's virtual network.
 * @property reachedThrough The way the socket reached the hub as its last state named it, empty before the first.
 * @property isPanelAllowed Whether the hub's last state lets this phone open its panel.
 * @property panelForward The loopback number the panel's forward listens on, 0 while it has none.
 */
data class HubView(
    val binding: HubBinding,
    val connection: HubConnection = HubConnection.CONNECTING,
    val software: String = "",
    val lastError: ChannelResult.Refused? = null,
    val services: List<ChannelServiceEntry> = emptyList(),
    val terminals: List<ChannelTerminal> = emptyList(),
    val connectedAddress: String = "",
    val hasConnected: Boolean = false,
    val droppedAtMillis: Long = 0,
    val jobs: HubJobs = HubJobs(),
    val jobError: ChannelResult.Refused? = null,
    val overlay: OverlayLine = OverlayLine(),
    val reachedThrough: String = "",
    val isPanelAllowed: Boolean = false,
    val panelForward: Int = 0,
) {
    /** Whether the socket is open and the hub serves this phone. */
    val isConnected: Boolean
        get() = connection == HubConnection.CONNECTED

    /** Whether the hub refused the binding's ticket: nothing runs, and Leave is the one action. */
    val isJoinRefused: Boolean
        get() = binding.isPending && connection == HubConnection.DOWN

    /** Whether the hub switched this client off. */
    val isDisabled: Boolean
        get() = connection == HubConnection.DISABLED

    /**
     * The published entries of one type, empty unless the hub serves this phone.
     *
     * @param type `web`, `port`, `ai`, `file` or `rdp`.
     * @return The entries.
     */
    fun servicesOf(type: String): List<ChannelServiceEntry> =
        if (isConnected) services.filter { it.type == type } else emptyList()
}
