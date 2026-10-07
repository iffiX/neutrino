package io.github.iffix.neutrino.channel

import java.net.InetAddress

/**
 * A network this phone holds an address in.
 *
 * @property address This phone's address there.
 * @property prefix The network's prefix length.
 */
data class ChannelLocalNetwork(val address: InetAddress, val prefix: Int) {
    /**
     * Whether an address lies inside this network.
     *
     * @param host The address.
     * @return True when both are of one family and share the first [prefix] bits.
     */
    fun holds(host: InetAddress): Boolean {
        val mine = address.address
        val theirs = host.address
        if (mine.size != theirs.size || prefix < 0) return false
        val bits = prefix.coerceAtMost(mine.size * 8)
        for (index in 0 until bits) {
            val mask = 0x80 ushr (index % 8)
            if ((mine[index / 8].toInt() and mask) != (theirs[index / 8].toInt() and mask)) return false
        }
        return true
    }
}
