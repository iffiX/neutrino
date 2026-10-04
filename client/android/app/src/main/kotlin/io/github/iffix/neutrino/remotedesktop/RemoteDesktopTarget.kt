package io.github.iffix.neutrino.remotedesktop

import io.github.iffix.neutrino.FORWARD_BIND_HOST
import io.github.iffix.neutrino.channel.ChannelResult
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * Where the viewer dials one shared desktop: the entry's forward on this phone's loopback, with
 * the seat password the hub's `service` stream handed over.
 *
 * @property name What the viewer's bar shows: `<hub>:<machine>`.
 * @property host The loopback address the forward listens on.
 * @property port The forward's loopback number.
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
         * Read a `service` stream's answer for an `rdp` entry, for a viewer that dials the entry's forward.
         *
         * @param name What the viewer's bar shows.
         * @param answer The stream's close: `{password}`, or the hub's refusal.
         * @param localPort The loopback number the entry's forward listens on.
         * @return The target, or the hub's refusal.
         */
        fun of(name: String, answer: ChannelResult<JsonObject>, localPort: Int): ChannelResult<RemoteDesktopTarget> {
            val material = when (answer) {
                is ChannelResult.Refused -> return answer
                is ChannelResult.Ok -> answer.value
            }
            val password = (material["password"] as? JsonPrimitive)?.content.orEmpty()
            return ChannelResult.Ok(RemoteDesktopTarget(name, FORWARD_BIND_HOST, localPort, password))
        }
    }
}
