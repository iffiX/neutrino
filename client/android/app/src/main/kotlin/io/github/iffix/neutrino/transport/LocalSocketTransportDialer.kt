package io.github.iffix.neutrino.transport

import android.net.LocalSocket
import android.net.LocalSocketAddress
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream

/**
 * Connections to the transport's Unix socket in the app's data directory.
 *
 * @param path The socket's path, as the library was started with.
 */
class LocalSocketTransportDialer(private val path: String) : TransportDialer {
    override fun dial(): TransportConnection {
        val socket = LocalSocket()
        try {
            socket.connect(LocalSocketAddress(path, LocalSocketAddress.Namespace.FILESYSTEM))
        } catch (error: IOException) {
            socket.close()
            throw error
        }
        return Connection(socket)
    }

    private class Connection(private val socket: LocalSocket) : TransportConnection {
        override val input: InputStream = socket.inputStream

        override val output: OutputStream = socket.outputStream

        override fun close() {
            try {
                socket.shutdownInput()
                socket.shutdownOutput()
            } catch (_: IOException) {
                // The transport already closed its end.
            }
            socket.close()
        }
    }
}
