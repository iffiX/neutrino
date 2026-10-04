package io.github.iffix.neutrino.binding

import io.github.iffix.neutrino.channel.ChannelOverlay
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * What this phone keeps of one hub it joined, in the desktop client's binding shape.
 *
 * @property id The key this phone keeps the binding under: the id the join returned, or, for a
 *   binding kept before its ticket was spent, an id made here.
 * @property name The name this phone joined under.
 * @property hubId The hub's id from its welcome.
 * @property hubName The hub's name from its welcome.
 * @property gatewayUrl The address that last answered.
 * @property gatewayUrls Every address the hub answers on, from the link and then each state.
 * @property fingerprint The pinned SHA-256 of the hub's certificate.
 * @property token The secret every hello carries; empty while the ticket is unspent.
 * @property ticket The link's ticket while it is unspent; empty once the join is done.
 * @property hubBindingId The id the hub gave a binding whose ticket was spent after it was kept;
 *   empty when [id] is the hub's own.
 * @property overlays What this phone joins the hub's virtual networks with, preferred first.
 * @property isOverlayOn Whether this phone was on the hub's virtual network when last seen; a start
 *   then connects it once.
 * @property overlayChoice The provider the person picked, empty for the hub's first.
 */
@Serializable
data class HubBinding(
    val id: String,
    val name: String = "",
    @SerialName("hub_id") val hubId: String = "",
    @SerialName("hub_name") val hubName: String = "",
    @SerialName("gateway_url") val gatewayUrl: String,
    @SerialName("gateway_urls") val gatewayUrls: List<String> = emptyList(),
    val fingerprint: String,
    val token: String,
    val ticket: String = "",
    @SerialName("hub_binding_id") val hubBindingId: String = "",
    val overlays: List<ChannelOverlay> = emptyList(),
    @SerialName("is_overlay_on") val isOverlayOn: Boolean = false,
    @SerialName("overlay_choice") val overlayChoice: String = "",
) {
    /** Every address the binding holds: the hub's list, and the one that last answered when it is not in it. */
    val storedUrls: List<String>
        get() = if (gatewayUrl in gatewayUrls || gatewayUrl.isEmpty()) gatewayUrls else gatewayUrls + gatewayUrl

    /** Whether the binding waits for its ticket to be spent: no hello goes before. */
    val isPending: Boolean
        get() = ticket.isNotEmpty()

    /** The id the hub knows the binding by. */
    val boundId: String
        get() = hubBindingId.ifEmpty { id }

    /** The name a screen shows: the hub's own, else its address. */
    val title: String
        get() = hubName.ifEmpty { gatewayUrl }

    /**
     * The addresses one connection round tries, in order.
     *
     * @param nameUrl The address the hub's name resolves to on this network, or empty.
     * @param preferredUrl The hub's address on the virtual network this phone is on, or empty.
     * @return The preferred address, the name's, the one that last answered, then the rest, each once.
     */
    fun candidateUrls(nameUrl: String, preferredUrl: String = ""): List<String> =
        (listOf(preferredUrl, nameUrl, gatewayUrl) + storedUrls).filter { it.isNotEmpty() }.distinct()
}
