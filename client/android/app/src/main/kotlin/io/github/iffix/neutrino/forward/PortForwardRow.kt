package io.github.iffix.neutrino.forward

import io.github.iffix.neutrino.channel.ChannelResult

/**
 * What one app's row, or a hub's panel, shows of its forwards.
 *
 * @property isInUse Whether the app is in use: from the first forward Use made until Stop.
 * @property localPort The loopback number the panel's forward listens on, 0 while it has none.
 * @property job The job running on the row, or null for none.
 * @property error The code the row's last job ended in, until its next press or a refresh.
 */
data class PortForwardRow(
    val isInUse: Boolean = false,
    val localPort: Int = 0,
    val job: PortForwardJob? = null,
    val error: ChannelResult.Refused? = null,
)
