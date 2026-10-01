package io.github.iffix.neutrino.channel

/**
 * The join a person started: running, or ended in a binding or a refusal.
 *
 * @property isJoining Whether the link is being checked and the binding written.
 * @property refusal Why the last join failed, shown under the link until the next press.
 * @property joinedId The binding the last join wrote, until the Join page has drawn it.
 */
data class HubJoin(
    val isJoining: Boolean = false,
    val refusal: ChannelResult.Refused? = null,
    val joinedId: String? = null,
)
