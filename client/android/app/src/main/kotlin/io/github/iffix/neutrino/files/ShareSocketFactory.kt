package io.github.iffix.neutrino.files

import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.Socket
import java.net.SocketAddress
import javax.net.SocketFactory

/**
 * The sockets a share is reached over: a connect bounded short, so an unreachable server fails
 * fast, and each read bounded long, so a slow large transfer is not taken for a dead server.
 *
 * @property connectTimeoutMillis How long reaching the server may take.
 * @property readTimeoutMillis How long one read may wait for the server.
 */
class ShareSocketFactory(val connectTimeoutMillis: Int, val readTimeoutMillis: Int) : SocketFactory() {
    override fun createSocket(): Socket = Bounded()

    override fun createSocket(host: String, port: Int): Socket = Bounded().apply {
        connect(InetSocketAddress(host, port))
    }

    override fun createSocket(host: String, port: Int, localHost: InetAddress, localPort: Int): Socket =
        createSocket(host, port)

    override fun createSocket(host: InetAddress, port: Int): Socket =
        Bounded().apply { connect(InetSocketAddress(host, port)) }

    override fun createSocket(address: InetAddress, port: Int, localAddress: InetAddress, localPort: Int): Socket =
        createSocket(address, port)

    private inner class Bounded : Socket() {
        init {
            soTimeout = readTimeoutMillis
        }

        override fun connect(endpoint: SocketAddress) = connect(endpoint, connectTimeoutMillis)
    }
}
