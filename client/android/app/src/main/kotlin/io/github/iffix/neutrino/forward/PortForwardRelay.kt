package io.github.iffix.neutrino.forward

import io.github.iffix.neutrino.FORWARD_BIND_HOST
import io.github.iffix.neutrino.FORWARD_BUFFER_BYTES
import io.github.iffix.neutrino.FORWARD_CONNECT_TIMEOUT_MILLIS
import java.io.Closeable
import java.io.IOException
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import kotlin.concurrent.thread

/**
 * One listening loopback port relayed to one published port, as the desktop client's relay
 * does: each accepted connection opens a plain socket to the published host and port, which the
 * virtual network or the LAN carries, and the two are copied into each other until both ends
 * close. With a token, each request's head and its response's head pass through
 * [WebTokenHeaders] first, then the bytes are copied.
 *
 * @property host The address the published port answers on.
 * @property port The published port number.
 * @param requestedPort The loopback number to listen on; 0 for any free one.
 * @param token A local-only web entry's token, sent as its cookie; empty to relay bytes only.
 * @param connectTimeoutMillis How long reaching the published port may take for one connection.
 */
open class PortForwardRelay(
    val host: String,
    val port: Int,
    private val requestedPort: Int,
    private val token: String = "",
    private val connectTimeoutMillis: Int = FORWARD_CONNECT_TIMEOUT_MILLIS,
) : Closeable {
    private val connections = mutableSetOf<Socket>()
    private var listener: ServerSocket? = null

    @Volatile
    private var isClosed = false

    /** The loopback number bound; 0 until started. */
    var localPort: Int = 0
        private set

    /** Whether the relay still listens. */
    val isActive: Boolean
        get() = listener != null && !isClosed

    /**
     * Bind the loopback and start accepting.
     *
     * @return The loopback number bound.
     * @throws IOException When the number cannot be bound.
     */
    open fun start(): Int {
        val bound = bind(requestedPort)
        listener = bound
        localPort = bound.localPort
        thread(isDaemon = true, name = "forward-$localPort") { accept(bound) }
        return localPort
    }

    /** Stop listening and close every open connection. */
    override fun close() {
        isClosed = true
        try {
            listener?.close()
        } catch (_: IOException) {
            // The listener was already gone.
        }
        val open = synchronized(connections) { connections.toList().also { connections.clear() } }
        for (socket in open) closeQuietly(socket)
    }

    private fun bind(number: Int): ServerSocket = ServerSocket().apply {
        reuseAddress = true
        try {
            bind(InetSocketAddress(InetAddress.getByName(FORWARD_BIND_HOST), number))
        } catch (error: IOException) {
            close()
            throw error
        }
    }

    private fun accept(server: ServerSocket) {
        while (!isClosed) {
            val client = try {
                server.accept()
            } catch (_: IOException) {
                break
            }
            if (isClosed) {
                closeQuietly(client)
                break
            }
            thread(isDaemon = true, name = "forward-$localPort-serve") { serve(client) }
        }
    }

    private fun serve(client: Socket) {
        val upstream = Socket()
        try {
            upstream.connect(InetSocketAddress(host, port), connectTimeoutMillis)
        } catch (_: IOException) {
            closeQuietly(client)
            closeQuietly(upstream)
            return
        }
        synchronized(connections) {
            if (isClosed) {
                closeQuietly(client)
                closeQuietly(upstream)
                return
            }
            connections += client
            connections += upstream
        }
        if (token.isEmpty()) {
            val outbound = thread(isDaemon = true, name = "forward-$localPort-out") { pump(client, upstream) }
            pump(upstream, client)
            outbound.join()
        } else {
            rewrite(client, upstream)
        }
        synchronized(connections) {
            connections -= client
            connections -= upstream
        }
        closeQuietly(client)
        closeQuietly(upstream)
    }

    private fun rewrite(client: Socket, upstream: Socket) {
        try {
            val (request, early) = WebTokenHeaders.read(client.getInputStream()) ?: return
            upstream.getOutputStream().apply {
                write(WebTokenHeaders.request(request, token).toByteArray(Charsets.ISO_8859_1))
                write(early)
                flush()
            }
            val outbound = thread(isDaemon = true, name = "forward-$localPort-out") { pump(client, upstream) }
            val answer = WebTokenHeaders.read(upstream.getInputStream())
            if (answer != null) {
                val (response, rest) = answer
                client.getOutputStream().apply {
                    write(WebTokenHeaders.response(response).toByteArray(Charsets.ISO_8859_1))
                    write(rest)
                    flush()
                }
                pump(upstream, client)
            } else {
                closeQuietly(client)
            }
            closeQuietly(upstream)
            outbound.join()
        } catch (_: IOException) {
            // Either side closed mid-head; both are closed below.
        }
    }

    private fun pump(source: Socket, destination: Socket) {
        val buffer = ByteArray(FORWARD_BUFFER_BYTES)
        try {
            val input = source.getInputStream()
            val output = destination.getOutputStream()
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                output.write(buffer, 0, count)
                output.flush()
            }
        } catch (_: IOException) {
            // One side closed; the end of stream is passed on below.
        }
        try {
            destination.shutdownOutput()
        } catch (_: IOException) {
            // The other side is gone already.
        }
    }

    private fun closeQuietly(socket: Socket) {
        try {
            socket.close()
        } catch (_: IOException) {
            // Already closed.
        }
    }
}
