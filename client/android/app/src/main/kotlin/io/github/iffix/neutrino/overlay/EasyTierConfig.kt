package io.github.iffix.neutrino.overlay

import io.github.iffix.neutrino.channel.ChannelOverlay

/** The TOML one manual EasyTier network runs from, as its core reads it. */
object EasyTierConfig {
    /**
     * The configuration of a manual network: the hub's network, met at the hub's peer, this
     * phone's address given by the network, no listener of its own.
     *
     * @param overlay The hub's EasyTier object, in manual mode.
     * @param instanceName The instance's name.
     * @param hostname The name this phone shows to the other members.
     * @return The TOML.
     */
    fun render(overlay: ChannelOverlay, instanceName: String, hostname: String): String = buildString {
        appendLine("instance_name = ${quoted(instanceName)}")
        appendLine("hostname = ${quoted(hostname)}")
        appendLine("dhcp = true")
        appendLine("listeners = []")
        appendLine()
        appendLine("[network_identity]")
        appendLine("network_name = ${quoted(overlay.networkName)}")
        appendLine("network_secret = ${quoted(overlay.networkSecret)}")
        appendLine()
        appendLine("[[peer]]")
        appendLine("uri = ${quoted(overlay.peer)}")
    }

    /**
     * A TOML basic string.
     *
     * @param text The text.
     * @return The text quoted, with every character TOML escapes escaped.
     */
    fun quoted(text: String): String = buildString {
        append('"')
        for (char in text) {
            when {
                char == '"' -> append("\\\"")
                char == '\\' -> append("\\\\")
                char == '\n' -> append("\\n")
                char == '\r' -> append("\\r")
                char == '\t' -> append("\\t")
                char.code < 0x20 || char.code == 0x7f -> append("\\u%04x".format(char.code))
                else -> append(char)
            }
        }
        append('"')
    }
}
