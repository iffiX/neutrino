package io.github.iffix.neutrino.channel

import io.github.iffix.neutrino.CLIENT_LINK_PREFIX
import io.github.iffix.neutrino.CLIENT_ROLE
import java.util.Base64
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.decodeFromJsonElement

/**
 * A client link from a hub's Clients page: `neutrino://enroll/<base64url>` over one JSON object,
 * pasted, or fetched for the [ShortEnrollmentLink] a QR code carries.
 *
 * @property urls Every address the hub answers on, in the hub's order, without a trailing slash.
 * @property ticket The enrolment ticket, spent by the join.
 * @property fingerprint The SHA-256 of the hub's certificate, lower-case hex.
 * @property overlays What this phone joins the hub's virtual networks with, the usable ones only.
 */
data class EnrollmentLink(
    val urls: List<String>,
    val ticket: String,
    val fingerprint: String,
    val overlays: List<ChannelOverlay>,
) {
    companion object {
        private val json = Json { ignoreUnknownKeys = true }

        /**
         * Read what a person pasted or scanned.
         *
         * @param text The link, or its bare payload without the scheme.
         * @return The link, or the refusal: `link_missing` for nothing, `link_unreadable` for
         *   something that is not a link, `link_incomplete` for a link without an address, a
         *   ticket or a fingerprint, `link_not_for_client {role}` for a device's link.
         */
        fun parse(text: String): ChannelResult<EnrollmentLink> {
            val trimmed = text.trim()
            if (trimmed.isEmpty()) return ChannelResult.refused("link_missing")
            val payload = decode(trimmed.removePrefix(CLIENT_LINK_PREFIX))
                ?: return ChannelResult.refused("link_unreadable")
            return fromObject(payload)
        }

        /**
         * Read the object a long link carries, or the one a short link's hub answered.
         *
         * @param payload The object.
         * @return The link, or the refusal [parse] names for a link of that object.
         */
        fun fromObject(payload: JsonObject): ChannelResult<EnrollmentLink> {
            val urls = cleanUrls(payload["urls"])
            val ticket = (payload["token"] as? JsonPrimitive)?.content.orEmpty()
            val fingerprint = (payload["fp"] as? JsonPrimitive)?.content.orEmpty().trim().lowercase()
            val role = (payload["role"] as? JsonPrimitive)?.content.orEmpty()
            if (urls.isEmpty() || ticket.isEmpty() || fingerprint.isEmpty()) {
                return ChannelResult.refused("link_incomplete")
            }
            if (role != CLIENT_ROLE) return ChannelResult.refused("link_not_for_client", "role" to role)
            return ChannelResult.Ok(EnrollmentLink(urls, ticket, fingerprint, cleanOverlays(payload["overlays"])))
        }

        /**
         * A list of addresses as a binding keeps them.
         *
         * @param value What a link, a state or a file carried.
         * @return Each non-blank string without its trailing slash, in order, each once.
         */
        fun cleanUrls(value: Any?): List<String> {
            val items = (value as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.content }
                ?: (value as? List<*>)?.mapNotNull { it as? String }
                ?: return emptyList()
            return items.map { it.trim().trimEnd('/') }.filter { it.isNotEmpty() }.distinct()
        }

        /**
         * The overlay objects a phone can join with, in the hub's order.
         *
         * @param value A JSON array of overlay objects.
         * @return The usable ones; an object of an unknown provider or missing a field is left out.
         */
        fun cleanOverlays(value: Any?): List<ChannelOverlay> {
            val items = value as? JsonArray ?: return emptyList()
            return items.mapNotNull { item ->
                try {
                    json.decodeFromJsonElement<ChannelOverlay>(item).takeIf { it.isUsable }
                } catch (_: SerializationException) {
                    null
                } catch (_: IllegalArgumentException) {
                    null
                }
            }
        }

        private fun decode(text: String): JsonObject? {
            val padded = text + "=".repeat((4 - text.length % 4) % 4)
            return try {
                val bytes = Base64.getUrlDecoder().decode(padded)
                json.parseToJsonElement(String(bytes, Charsets.UTF_8)) as? JsonObject
            } catch (_: IllegalArgumentException) {
                null
            } catch (_: SerializationException) {
                null
            }
        }
    }
}
