package io.github.iffix.neutrino.overlay

import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.longOrNull

/**
 * One running EasyTier instance as its core reports it.
 *
 * @property name The instance's name.
 * @property address This phone's address on the network, empty until the network gives one.
 * @property prefix The network's prefix length.
 * @property proxyCidrs The subnets other members route into the network.
 * @property peerAddresses The addresses of the other members the core has a route to.
 * @property isRunning Whether the instance runs.
 * @property error The core's last error, empty for none.
 */
data class EasyTierInstance(
    val name: String,
    val address: String,
    val prefix: Int,
    val proxyCidrs: List<String>,
    val peerAddresses: Set<String>,
    val isRunning: Boolean,
    val error: String,
) {
    companion object {
        private val json = Json { ignoreUnknownKeys = true }

        /**
         * Read what `collectNetworkInfos` returns.
         *
         * @param text `{"map": {name: running info}}`, or null.
         * @return Every instance, in the core's order; nothing for text that does not read.
         */
        fun parse(text: String?): List<EasyTierInstance> {
            val root = try {
                text?.let { json.parseToJsonElement(it) as? JsonObject }
            } catch (_: SerializationException) {
                null
            } ?: return emptyList()
            val map = root["map"] as? JsonObject ?: return emptyList()
            return map.mapNotNull { (name, value) -> (value as? JsonObject)?.let { instanceOf(name, it) } }
        }

        private fun instanceOf(name: String, info: JsonObject): EasyTierInstance {
            val inet = (info["my_node_info"] as? JsonObject)?.get("virtual_ipv4") as? JsonObject
            val prefix = ((inet?.get("network_length") as? JsonPrimitive)?.longOrNull ?: 0L).toInt()
            val routes = (info["routes"] as? JsonArray ?: JsonArray(emptyList())).mapNotNull { it as? JsonObject }
            val cidrs = routes.flatMap { route ->
                (route["proxy_cidrs"] as? JsonArray).orEmpty().mapNotNull { (it as? JsonPrimitive)?.content }
            }.distinct()
            return EasyTierInstance(
                name = name,
                address = addressOf(inet),
                prefix = prefix,
                proxyCidrs = cidrs,
                peerAddresses = routes.map {
                    addressOf(it["ipv4_addr"] as? JsonObject)
                }.filter { it.isNotEmpty() }.toSet(),
                isRunning = (info["running"] as? JsonPrimitive)?.booleanOrNull ?: false,
                error = (info["error_msg"] as? JsonPrimitive)?.takeIf { it.isString }?.content.orEmpty(),
            )
        }

        private fun addressOf(inet: JsonObject?): String {
            val raw = ((inet?.get("address") as? JsonObject)?.get("addr") as? JsonPrimitive)?.longOrNull ?: 0L
            return if (raw == 0L) "" else dotted(raw)
        }

        private fun dotted(address: Long): String =
            listOf(24, 16, 8, 0).joinToString(".") { ((address shr it) and 0xff).toString() }
    }
}
