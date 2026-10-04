package io.github.iffix.neutrino.netbird

import io.github.iffix.neutrino.CarriedCore
import io.github.iffix.neutrino.channel.ChannelOverlay
import io.github.iffix.neutrino.overlay.OverlayEngine
import io.github.iffix.neutrino.overlay.OverlayPart
import java.io.File

/** NetBird's part of the app, which the edition table loads by its class name. */
object NetbirdPart : OverlayPart {
    override val provider: String = OVERLAY_PROVIDER_NETBIRD

    override val title: String = "NetBird"

    override val carriedCore: CarriedCore =
        CarriedCore("NetBird", OVERLAY_NETBIRD_VERSION, "BSD-3-Clause", OVERLAY_NETBIRD_SOURCE_URL)

    override val hubNetwork: String = OVERLAY_NETBIRD_NETWORK

    override fun isUsable(overlay: ChannelOverlay): Boolean = overlay.setupKey.isNotBlank()

    override fun hubName(overlay: ChannelOverlay): String = overlay.fqdn

    override fun engine(dir: File, deviceName: String, version: String): OverlayEngine =
        NetbirdOverlayEngine(dir, deviceName, version)
}
