package io.github.iffix.neutrino.channel

import io.github.iffix.neutrino.CLIENT_LINK_PREFIX
import io.github.iffix.neutrino.CLIENT_LINK_SHORT_MARK
import java.net.URI
import java.net.URISyntaxException

/**
 * The short link a hub's QR code carries: `neutrino://enroll/<ticket>@<host>:<port>/<sha256-hex>`.
 *
 * @property ticket The enrolment ticket.
 * @property baseUrl The hub's address the long link's object is fetched from, `https://host:port`.
 * @property fingerprint The SHA-256 of the hub's certificate, lower-case hex.
 */
data class ShortEnrollmentLink(val ticket: String, val baseUrl: String, val fingerprint: String) {
    companion object {
        private val hex = Regex("[0-9a-f]{64}")

        /**
         * Whether a text is a short link rather than a long one.
         *
         * @param text What a person pasted or scanned.
         * @return Whether it carries the short link's mark.
         */
        fun isShort(text: String): Boolean = CLIENT_LINK_SHORT_MARK in text.trim().removePrefix(CLIENT_LINK_PREFIX)

        /**
         * Read a short link.
         *
         * @param text The short link, or the same without its scheme.
         * @return The link, or `link_unreadable` when a part is missing or the fingerprint is not 64
         *   hex characters.
         */
        fun parse(text: String): ChannelResult<ShortEnrollmentLink> {
            val body = text.trim().removePrefix(CLIENT_LINK_PREFIX)
            val ticket = body.substringBefore(CLIENT_LINK_SHORT_MARK)
            val rest = body.substringAfter(CLIENT_LINK_SHORT_MARK)
            val address = rest.substringBeforeLast('/')
            val fingerprint = rest.substringAfterLast('/').lowercase()
            val uri = try {
                URI("https://$address")
            } catch (_: URISyntaxException) {
                return ChannelResult.refused("link_unreadable")
            }
            if (ticket.isEmpty() || uri.host.isNullOrEmpty() || uri.port < 0 || !hex.matches(fingerprint)) {
                return ChannelResult.refused("link_unreadable")
            }
            return ChannelResult.Ok(ShortEnrollmentLink(ticket, "https://$address", fingerprint))
        }
    }
}
