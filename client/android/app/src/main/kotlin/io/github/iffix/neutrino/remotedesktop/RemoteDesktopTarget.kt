package io.github.iffix.neutrino.remotedesktop

import io.github.iffix.neutrino.channel.ChannelResult
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.intOrNull

/**
 * Where one shared desktop answers, as the hub's `service` stream hands it over.
 *
 * @property name What the viewer's bar shows: `<hub>:<machine>`.
 * @property host The address.
 * @property port RustDesk's direct port.
 * @property password The seat password of the machine sharing it.
 * @property choice The codec and quality the session asks for.
 * @property platformOs The `platform_os` the entry carries, or empty when it names none.
 */
data class RemoteDesktopTarget(
    val name: String,
    val host: String,
    val port: Int,
    val password: String,
    val choice: RemoteDesktopChoice = RemoteDesktopChoice(),
    val platformOs: String = "",
) {
    override fun toString(): String = "RemoteDesktopTarget(name=$name, host=$host, port=$port)"

    companion object {
        /**
         * Read a `service` stream's answer for an `rdp` entry.
         *
         * @param name What the viewer's bar shows.
         * @param answer The stream's close: `{host, port, password}`, or the hub's refusal.
         * @return The target, the hub's refusal, or `rdp_no_address` when the material names no host or port.
         */
        fun of(name: String, answer: ChannelResult<JsonObject>): ChannelResult<RemoteDesktopTarget> {
            val material = when (answer) {
                is ChannelResult.Refused -> return answer
                is ChannelResult.Ok -> answer.value
            }
            val host = (material["host"] as? JsonPrimitive)?.content.orEmpty()
            val port = (material["port"] as? JsonPrimitive)?.intOrNull ?: 0
            val password = (material["password"] as? JsonPrimitive)?.content.orEmpty()
            if (host.isEmpty() || port <= 0) return ChannelResult.refused("rdp_no_address")
            return ChannelResult.Ok(RemoteDesktopTarget(name, host, port, password))
        }
    }
}
