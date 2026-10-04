package io.github.iffix.neutrino.files

import io.github.iffix.neutrino.CLIENT_SHARE_HOLD_S
import io.github.iffix.neutrino.channel.ChannelServiceEntry
import io.github.iffix.neutrino.channel.HubView
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive

/**
 * One published share, as a root of the system's Files.
 *
 * @property key The root's id: the hub's binding and the entry, `<binding>~<entry>`.
 * @property title The share's title.
 * @property host The server's address.
 * @property share The share's name.
 * @property users The accounts the hub names for it; empty when it names none.
 * @property summary Who provides it, for the root's second line.
 * @property bindingId The hub's binding, whose channel carries the share's connections.
 * @property entryId The `file` entry a `connect` stream names for each connection.
 * @property isReconnecting Whether its hub's channel dropped less than a minute ago and is not back yet.
 */
data class ShareRoot(
    val key: String,
    val title: String,
    val host: String,
    val share: String,
    val users: List<String>,
    val summary: String,
    val bindingId: String,
    val entryId: String,
    val isReconnecting: Boolean = false,
) {
    companion object {
        /**
         * The share a `file` entry names.
         *
         * @param hub The hub that publishes it.
         * @param entry The entry.
         * @return The root, or null for an entry that names no host or share, or another protocol.
         */
        fun of(hub: HubView, entry: ChannelServiceEntry): ShareRoot? {
            val host = entry.text("host")
            val share = entry.text("share")
            if (entry.type != "file" || entry.text("protocol") != "smb" || host.isEmpty() ||
                share.isEmpty()
            ) {
                return null
            }
            val users = (entry.payload["users"] as? JsonArray).orEmpty().mapNotNull { (it as? JsonPrimitive)?.content }
            val device = entry.deviceName.ifEmpty { host }
            return ShareRoot(
                key = "${hub.binding.id}~${entry.id}",
                title = entry.title,
                host = host,
                share = share,
                users = users,
                summary = "${hub.binding.title}:$device",
                bindingId = hub.binding.id,
                entryId = entry.id,
            )
        }

        /**
         * Every share the connected hubs publish, and the shares of a hub whose channel dropped
         * less than [CLIENT_SHARE_HOLD_S] ago, marked as reconnecting.
         *
         * @param hubs Every hub.
         * @param nowMillis The time in the sessions' clock.
         * @return The roots, in the hubs' order.
         */
        fun all(hubs: List<HubView>, nowMillis: Long): List<ShareRoot> = hubs.flatMap { hub ->
            when {
                hub.isConnected -> hub.servicesOf("file").mapNotNull { of(hub, it) }

                isHeld(hub, nowMillis) ->
                    hub.services.filter { it.type == "file" }.mapNotNull { of(hub, it)?.copy(isReconnecting = true) }

                else -> emptyList()
            }
        }

        /**
         * When the first hold of a dropped hub's shares ends.
         *
         * @param hubs Every hub.
         * @param nowMillis The time in the sessions' clock.
         * @return The end in the same clock, or null while no hub's shares are held.
         */
        fun holdEndsAt(hubs: List<HubView>, nowMillis: Long): Long? =
            hubs.filter { isHeld(it, nowMillis) }.minOfOrNull { it.droppedAtMillis + CLIENT_SHARE_HOLD_S * 1000 }

        private fun isHeld(hub: HubView, nowMillis: Long): Boolean = !hub.isConnected && !hub.isDisabled &&
            hub.droppedAtMillis > 0 && nowMillis - hub.droppedAtMillis < CLIENT_SHARE_HOLD_S * 1000
    }
}
