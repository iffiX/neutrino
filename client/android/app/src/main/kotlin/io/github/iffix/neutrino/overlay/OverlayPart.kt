package io.github.iffix.neutrino.overlay

import io.github.iffix.neutrino.CarriedCore
import io.github.iffix.neutrino.channel.ChannelOverlay
import java.io.File

/** What a left-out feature's virtual network gives the app, through the edition table. */
interface OverlayPart {
    /** The provider name its overlay objects carry. */
    val provider: String

    /** The name the picker and the line show it by. */
    val title: String

    /** Its core, for the About card. */
    val carriedCore: CarriedCore

    /** The network its members' addresses sit in, as `a.b.c.d/n`, where the hub's own is looked for. */
    val hubNetwork: String

    /**
     * Whether an overlay object carries everything this network needs.
     *
     * @param overlay The object.
     * @return True when it can be joined.
     */
    fun isUsable(overlay: ChannelOverlay): Boolean

    /**
     * The hub's name on this network, for a hub no address names there.
     *
     * @param overlay The object.
     * @return The name, empty for none.
     */
    fun hubName(overlay: ChannelOverlay): String

    /**
     * A new engine for this network.
     *
     * @param dir Where this hub's state of the network lives.
     * @param deviceName The name this phone joins under.
     * @param version The app's version.
     * @return The engine, not yet started.
     */
    fun engine(dir: File, deviceName: String, version: String): OverlayEngine
}
