package io.github.iffix.neutrino.binding

import io.github.iffix.neutrino.channel.ChannelOverlay
import java.security.MessageDigest
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * What this phone keeps of one hub it joined, in the desktop client's binding shape.
 *
 * @property id The key this phone keeps the binding under, made here when the link was read, and
 *   the name the transport knows the hub by.
 * @property name The name this phone joined under.
 * @property hubId The hub's id from its welcome.
 * @property hubName The hub's name from its welcome.
 * @property gatewayUrl The address that last answered.
 * @property gatewayUrls Every address the hub answers on, from the link and then each state.
 * @property hubKey The hub's static public key, 64 lowercase hex characters; empty in a binding of 0.5.
 * @property privateKey This phone's static private key for the hub, 64 lowercase hex characters,
 *   made when the link was read.
 * @property token The secret the hub keeps by its digest; empty while the ticket is unspent.
 * @property ticket The link's ticket while it is unspent; empty once the join is done.
 * @property hubBindingId The id the hub gave the binding when its ticket was spent.
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
    @SerialName("hub_key") val hubKey: String = "",
    @SerialName("private_key") val privateKey: String = "",
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

    /** Whether the binding is of 0.5's shape, pinned by a certificate this build cannot check. */
    val isKeyMissing: Boolean
        get() = hubKey.isEmpty() || privateKey.isEmpty()

    /** The id the hub knows the binding by. */
    val boundId: String
        get() = hubBindingId.ifEmpty { id }

    /** The name a screen shows: the hub's own, else its address. */
    val title: String
        get() = hubName.ifEmpty { gatewayUrl }

    /** The psk a bound knock carries: the SHA-256 of the token, 64 lowercase hex characters. */
    val psk: String
        get() = MessageDigest.getInstance("SHA-256").digest(token.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }
}
