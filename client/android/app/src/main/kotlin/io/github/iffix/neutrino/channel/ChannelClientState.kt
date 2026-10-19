package io.github.iffix.neutrino.channel

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * What a hub says is to be true for this phone: the `state` frame's sections.
 *
 * @property hash What the next report names back.
 * @property isDisabled Whether the hub switched this client off.
 * @property services The published list, resolved for the address this socket came from.
 * @property urls Every address the hub answers the channel on.
 * @property sshRelayUrl The member of [urls] that is the SSH relay's address, empty while it adds none.
 * @property sakurafrpUrl The member of [urls] that is SakuraFrp's address, empty while it adds none.
 * @property openfrpUrl The member of [urls] that is OpenFrp's address, empty while it adds none.
 * @property overlays What this phone joins each of the hub's virtual networks with, preferred first.
 * @property terminals The managed machines this phone may open a shell on.
 * @property isPanelAllowed Whether this phone may open the hub's panel through `connect {is_panel: true}`.
 * @property reachedThrough The way this phone's socket reached the hub: `lan`, `netbird`, `easytier`,
 *   `ssh_relay`, `direct`, `sakurafrp` or `openfrp`.
 */
@Serializable
data class ChannelClientState(
    val hash: String,
    @SerialName("is_disabled") val isDisabled: Boolean = false,
    val services: List<ChannelServiceEntry> = emptyList(),
    val urls: List<String> = emptyList(),
    @SerialName("ssh_relay_url") val sshRelayUrl: String = "",
    @SerialName("sakurafrp_url") val sakurafrpUrl: String = "",
    @SerialName("openfrp_url") val openfrpUrl: String = "",
    val overlays: List<ChannelOverlay> = emptyList(),
    val terminals: List<ChannelTerminal> = emptyList(),
    @SerialName("is_panel_allowed") val isPanelAllowed: Boolean = false,
    @SerialName("reached_through") val reachedThrough: String = "",
) {
    /** The address of each path through a server, empty while the hub names none. */
    val serverUrls: Map<ChannelPath, String>
        get() = mapOf(
            ChannelPath.SSH_RELAY to sshRelayUrl,
            ChannelPath.SAKURAFRP to sakurafrpUrl,
            ChannelPath.OPENFRP to openfrpUrl,
        )
}
