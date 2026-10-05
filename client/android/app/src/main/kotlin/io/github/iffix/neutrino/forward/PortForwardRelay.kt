package io.github.iffix.neutrino.forward

import android.util.Log
import io.github.iffix.neutrino.CLIENT_LOG_TAG
import io.github.iffix.neutrino.ConnectRefusedException
import io.github.iffix.neutrino.FORWARD_BIND_HOST
import io.github.iffix.neutrino.FORWARD_BUFFER_BYTES
import io.github.iffix.neutrino.FORWARD_CLOSE_WAIT_MILLIS
import io.github.iffix.neutrino.channel.ChannelConnectSocket
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.ChannelStream
import java.io.IOException
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import kotlin.concurrent.thread

/**
 * One listening loopback port whose every accepted connection is one `connect` stream to the
 * hub: the two are copied into each other, and when either ends, what was read is written and
 * both close. No connection dials a device address; the stream's open names the far end.
 *
 * @property name What the log calls the far end.
 * @param open Opens one `connect` stream for one accepted connection.
 * @param requestedPort The loopback number to listen on; 0 for any free one.
 */
open class PortForwardRelay(
    override val name: String,
    private val open: () -> ChannelResult<ChannelStream>,
    private val requestedPort: Int,
) : PortForwardListener {
    private val connections = mutableSetOf<Socket>()
    private var listener: ServerSocket? = null
    private var acceptor: Thread? = null

    @Volatile
    private var isClosed = false

    /** The loopback number bound; 0 until started. */
    final override var localPort: Int = 0
        private set

    /** Whether the relay still listens. */
    override val isActive: Boolean
        get() = listener != null && !isClosed

    /**
     * Bind the loopback and start accepting.
     *
     * @return The loopback number bound.
     * @throws IOException When the number cannot be bound, or the forward was closed first.
     */
    override fun start(): Int {
        val bound = bind(requestedPort)
        listener = bound
        if (isClosed) {
            bound.close()
            throw IOException("the forward was closed before it listened")
        }
        localPort = bound.localPort
        acceptor = thread(isDaemon = true, name = "forward-$localPort") { accept(bound) }
        return localPort
    }

    /** Stop listening and close every open connection; the loopback number is free once it returns. */
    override fun close() {
        isClosed = true
        try {
            listener?.close()
        } catch (_: IOException) {
            // The listener was already gone.
        }
        acceptor?.takeIf { it != Thread.currentThread() }?.join(FORWARD_CLOSE_WAIT_MILLIS)
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
        val upstream = ChannelConnectSocket(open)
        try {
            upstream.open()
        } catch (error: IOException) {
            Log.i(CLIENT_LOG_TAG, "a connection to $name was not opened: ${error.message}")
            closeQuietly(client)
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
        val outbound = thread(isDaemon = true, name = "forward-$localPort-out") { pump(client, upstream) }
        pump(upstream, client)
        outbound.join()
        synchronized(connections) {
            connections -= client
            connections -= upstream
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
        } catch (error: ConnectRefusedException) {
            Log.i(CLIENT_LOG_TAG, "the hub ended a connection to $name: ${error.code}")
        } catch (_: IOException) {
            // One side closed; both close below.
        }
        closeQuietly(source)
        closeQuietly(destination)
    }

    private fun closeQuietly(socket: Socket) {
        try {
            socket.close()
        } catch (_: IOException) {
            // Already closed.
        }
    }
}
