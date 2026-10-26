package io.github.iffix.neutrino.transport

/** Opens connections to the transport's local socket. */
fun interface TransportDialer {
    /**
     * Open one connection.
     *
     * @return The connection, before its first line.
     * @throws java.io.IOException When the socket does not take it.
     */
    fun dial(): TransportConnection
}
