package io.github.iffix.neutrino.channel

/**
 * A hub whose row went because it no longer knows this phone, shown on the Hubs page for a minute.
 *
 * @property hubTitle The hub's name as its row showed it.
 * @property refusal The code that removed it.
 */
data class HubNotice(val hubTitle: String, val refusal: ChannelResult.Refused)
