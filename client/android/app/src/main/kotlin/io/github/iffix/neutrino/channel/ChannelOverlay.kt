package io.github.iffix.neutrino.channel

import io.github.iffix.neutrino.OVERLAY_EASYTIER_MODE_CONSOLE
import io.github.iffix.neutrino.OVERLAY_EASYTIER_MODE_MANUAL
import io.github.iffix.neutrino.OVERLAY_PROVIDER_EASYTIER
import io.github.iffix.neutrino.OVERLAY_PROVIDER_NETBIRD
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * What this phone joins one of a hub's virtual networks with, from the link and each `state`.
 *
 * @property provider `netbird` or `easytier`.
 * @property mode EasyTier's mode, `manual` or `console`; empty for NetBird.
 * @property setupKey NetBird's reusable setup key.
 * @property managementUrl NetBird's management plane; empty for NetBird's own.
 * @property fqdn The hub's name on the NetBird network.
 * @property networkName The EasyTier network, in manual mode.
 * @property networkSecret Its secret.
 * @property peer The address the EasyTier network is met at, in manual mode.
 * @property configServer The EasyTier console with its account token, in console mode.
 * @property isSecureMode Whether the console is spoken to over its secure tunnel.
 * @property hubAddress The hub's own address on the EasyTier network, empty when not known.
 */
@Serializable
data class ChannelOverlay(
    val provider: String,
    val mode: String = "",
    @SerialName("setup_key") val setupKey: String = "",
    @SerialName("management_url") val managementUrl: String = "",
    val fqdn: String = "",
    @SerialName("network_name") val networkName: String = "",
    @SerialName("network_secret") val networkSecret: String = "",
    val peer: String = "",
    @SerialName("config_server") val configServer: String = "",
    @SerialName("is_secure_mode") val isSecureMode: Boolean = false,
    @SerialName("hub_address") val hubAddress: String = "",
) {
    /** The EasyTier mode this object runs, `manual` when a hub named none. */
    val easyTierMode: String
        get() = mode.ifEmpty { OVERLAY_EASYTIER_MODE_MANUAL }

    /** Whether this object carries everything its provider and mode need. */
    val isUsable: Boolean
        get() = when (provider) {
            OVERLAY_PROVIDER_NETBIRD -> setupKey.isNotBlank()

            OVERLAY_PROVIDER_EASYTIER -> when (easyTierMode) {
                OVERLAY_EASYTIER_MODE_MANUAL -> networkName.isNotBlank() && networkSecret.isNotBlank() &&
                    peer.isNotBlank()

                OVERLAY_EASYTIER_MODE_CONSOLE -> configServer.isNotBlank()

                else -> false
            }

            else -> false
        }

    /** The name the picker shows it by. */
    val title: String
        get() = if (provider == OVERLAY_PROVIDER_NETBIRD) "NetBird" else "EasyTier"
}
