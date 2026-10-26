package io.github.iffix.neutrino.transport

import io.github.iffix.neutrino.channel.ChannelResult

/**
 * A forward's listener stopped: a UDP forward whose stream the hub or the agent closed with a code.
 *
 * @property listen The address it listened on, `127.0.0.1:<port>`.
 * @property protocol `tcp` or `udp`.
 * @property refusal Why, `port_taken {port}` among the codes; null when it carries none.
 */
data class TransportForwardEnd(val listen: String, val protocol: String, val refusal: ChannelResult.Refused?)
