package io.github.iffix.neutrino.forward

import io.github.iffix.neutrino.channel.ChannelResult

/**
 * What one entry's row shows of its forward.
 *
 * @property localPort The loopback number it listens on, 0 while not forwarded.
 * @property job The job running on the row, or null for none.
 * @property error The code the row's last job ended in, until its next press or a refresh.
 */
data class PortForwardRow(
    val localPort: Int = 0,
    val job: PortForwardJob? = null,
    val error: ChannelResult.Refused? = null,
) {
    /** Whether the loopback listens. */
    val isForwarded: Boolean
        get() = localPort != 0
}
