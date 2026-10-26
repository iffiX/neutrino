package io.github.iffix.neutrino.transport

/** The transport the app embeds: one call starts it on its local channel, one stops it. */
interface TransportLibrary {
    /**
     * Start the transport, listening on its local channel.
     *
     * @param directory The app's own data directory, where the transport makes `transport.sock`.
     * @param secret The 64 hex characters every local connection opens with.
     * @return The path of the socket the transport listens on: in [directory], or in a directory of
     *   its own when that path is past the system's limit for a socket's path.
     * @throws io.github.iffix.neutrino.TransportMissingException When this build carries no transport.
     * @throws java.io.IOException When the transport could not start.
     */
    fun start(directory: String, secret: String): String

    /** Stop the transport: every session and every forward ends. */
    fun stop()
}
