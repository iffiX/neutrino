package io.github.iffix.neutrino.files

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
 */
data class ShareRoot(
    val key: String,
    val title: String,
    val host: String,
    val share: String,
    val users: List<String>,
    val summary: String,
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
            )
        }

        /**
         * Every share the connected hubs publish.
         *
         * @param hubs Every hub.
         * @return The roots, in the hubs' order.
         */
        fun all(hubs: List<HubView>): List<ShareRoot> =
            hubs.filter { it.isConnected }.flatMap { hub -> hub.servicesOf("file").mapNotNull { of(hub, it) } }
    }
}
