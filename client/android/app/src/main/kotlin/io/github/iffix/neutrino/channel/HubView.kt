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
 * @property jobs The actions running on the hub.
 * @property jobError The code the last leave ended in, kept until the next press on the row or a refresh.
 * @property overlay The hub's virtual network.
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
    val jobs: HubJobs = HubJobs(),
    val jobError: ChannelResult.Refused? = null,
    val overlay: OverlayLine = OverlayLine(),
) {
    /** Whether the socket is open and the hub serves this phone. */
    val isConnected: Boolean
        get() = connection == HubConnection.CONNECTED

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
