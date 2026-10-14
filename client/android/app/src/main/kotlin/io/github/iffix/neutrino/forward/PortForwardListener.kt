package io.github.iffix.neutrino.forward

import java.io.Closeable
import java.io.IOException

/** One forward's socket on the loopback: a TCP listener, or a UDP entry's one socket. */
interface PortForwardListener : Closeable {
    /** What the log calls the far end. */
    val name: String

    /** The loopback number bound; 0 until started. */
    val localPort: Int

    /** Whether the forward still listens. */
    val isActive: Boolean

    /**
     * Bind the loopback and start carrying.
     *
     * @return The loopback number bound.
     * @throws IOException When the number cannot be bound, or the forward's stream cannot be opened.
     */
    fun start(): Int

    /**
     * The hub's channel opened or closed. A TCP forward accepts only while it is open and stays
     * bound meanwhile; a UDP forward carries on as it is.
     *
     * @param isOpen Whether the hub has a channel now.
     */
    fun channelChanged(isOpen: Boolean) = Unit
}
