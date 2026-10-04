package io.github.iffix.neutrino.channel

import java.util.UUID

/**
 * A hub whose row went because it no longer knows this phone, shown on the Hubs page until it is
 * closed, a refresh, or a minute has passed.
 *
 * @property hubTitle The hub's name as its row showed it.
 * @property refusal The code that removed it.
 * @property id What tells two notices of the same hub and code apart.
 */
data class HubNotice(
    val hubTitle: String,
    val refusal: ChannelResult.Refused,
    val id: String = UUID.randomUUID().toString(),
)
