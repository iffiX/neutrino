package io.github.iffix.neutrino.forward

import android.util.Log
import io.github.iffix.neutrino.CLIENT_LOG_TAG
import io.github.iffix.neutrino.CLIENT_UDP_DATAGRAM_BYTES_MAX
import io.github.iffix.neutrino.CLIENT_UDP_HELD_DATAGRAMS_MAX
import io.github.iffix.neutrino.CLIENT_UDP_RETRY_MILLIS
import io.github.iffix.neutrino.CLIENT_UDP_SOURCES_MAX
import io.github.iffix.neutrino.CLIENT_UDP_SOURCE_BYTES
import io.github.iffix.neutrino.ConnectRefusedException
import io.github.iffix.neutrino.FORWARD_BIND_HOST
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.ChannelStream
import java.io.IOException
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.SocketAddress
import java.nio.ByteBuffer
import kotlin.concurrent.thread
import kotlinx.coroutines.runBlocking

/**
 * A UDP `port` entry's forward: one UDP socket on `127.0.0.1:<local port>` and one `connect`
 * stream. Each datagram goes into the stream as `<u16 source><datagram>`, `source` being the port
 * it came from, whose address the forward remembers for at most 64 sources, the one idle the
 * longest giving way; a frame from the stream goes to the remembered address of its `source`, and
 * one for a source no longer remembered is dropped. A datagram the hub's credit does not cover is
 * dropped; up to 16 wait only while an open waits for its first credit.
 *
 * The stream opens at [start], and again at the first datagram that finds none. The stream
 * opened at [start] closed with a code before any datagram went into it ends the forward, as the
 * answer to Connect; a later refusal leaves the forward listening, and a datagram tries again at
 * most once a second. Both are told to [onRefused].
 *
 * @property name What the log calls the far end.
 * @param open Opens the forward's `connect` stream.
 * @param requestedPort The loopback number to bind; 0 for any free one.
 * @param onRefused Called with a refusal and whether it ended the forward.
 * @param clock The time in milliseconds the retry is measured by.
 */
class PortForwardUdpRelay(
    override val name: String,
    private val open: () -> ChannelResult<ChannelStream>,
    private val requestedPort: Int,
    private val onRefused: (ChannelResult.Refused, Boolean) -> Unit,
    private val clock: () -> Long = System::currentTimeMillis,
) : PortForwardListener {
    private val lock = Any()
    private val held = ArrayDeque<ByteArray>()
    private val sources = object : LinkedHashMap<Int, SocketAddress>(CLIENT_UDP_SOURCES_MAX, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<Int, SocketAddress>): Boolean =
            size > CLIENT_UDP_SOURCES_MAX
    }

    @Volatile
    private var socket: DatagramSocket? = null
    private var stream: ChannelStream? = null
    private var isCredited = false
    private var isFirstStream = false
    private var hasSent = false
    private var refusedAt = Long.MIN_VALUE / 2

    @Volatile
    private var isClosed = false

    /** The loopback number bound; 0 until started. */
    override var localPort: Int = 0
        private set

    /** Whether the forward still listens. */
    override val isActive: Boolean
        get() = socket != null && !isClosed

    /**
     * Bind the loopback, open the stream, and start carrying datagrams.
     *
     * @return The loopback number bound.
     * @throws IOException When the number cannot be bound.
     * @throws ConnectRefusedException When the stream cannot be opened.
     */
    override fun start(): Int {
        val bound = DatagramSocket(null as SocketAddress?).apply {
            try {
                bind(InetSocketAddress(InetAddress.getByName(FORWARD_BIND_HOST), requestedPort))
            } catch (error: IOException) {
                close()
                throw error
            }
        }
        val first = when (val opened = open()) {
            is ChannelResult.Refused -> {
                bound.close()
                throw ConnectRefusedException(opened.code, opened.params)
            }

            is ChannelResult.Ok -> opened.value
        }
        socket = bound
        localPort = bound.localPort
        synchronized(lock) { carry(first, isFirst = true) }
        thread(isDaemon = true, name = "forward-udp-$localPort") { receive(bound) }
        return localPort
    }

    /** Close the socket and end the stream. */
    override fun close() {
        isClosed = true
        socket?.close()
        val ending = synchronized(lock) {
            held.clear()
            stream.also { stream = null }
        }
        ending?.close()
    }

    private fun receive(bound: DatagramSocket) {
        val buffer = ByteArray(CLIENT_UDP_DATAGRAM_BYTES_MAX)
        while (!isClosed) {
            val packet = DatagramPacket(buffer, buffer.size)
            try {
                bound.receive(packet)
            } catch (_: IOException) {
                break
            }
            val from = packet.socketAddress as? InetSocketAddress ?: continue
            val frame = ByteBuffer.allocate(CLIENT_UDP_SOURCE_BYTES + packet.length)
                .putShort(from.port.toShort())
                .put(packet.data, packet.offset, packet.length)
                .array()
            synchronized(lock) { sources[from.port] = from }
            forward(frame)
        }
    }

    private fun forward(frame: ByteArray) {
        val refusal = synchronized(lock) {
            if (isClosed) return
            val open = when (val current = stream?.let { ChannelResult.Ok(it) } ?: reopen() ?: return) {
                is ChannelResult.Refused -> return@synchronized current
                is ChannelResult.Ok -> current.value
            }
            hasSent = true
            if (isCredited) {
                open.trySend(frame)
            } else if (held.size < CLIENT_UDP_HELD_DATAGRAMS_MAX) {
                held.addLast(frame)
            }
            null
        }
        refusal?.let { onRefused(it, false) }
    }

    private fun reopen(): ChannelResult<ChannelStream>? {
        if (clock() - refusedAt < CLIENT_UDP_RETRY_MILLIS) return null
        return open().also { opened ->
            when (opened) {
                is ChannelResult.Refused -> refusedAt = clock()
                is ChannelResult.Ok -> carry(opened.value, isFirst = false)
            }
        }
    }

    private fun carry(opened: ChannelStream, isFirst: Boolean) {
        stream = opened
        isFirstStream = isFirst
        isCredited = false
        hasSent = false
        held.clear()
        thread(isDaemon = true, name = "forward-udp-$localPort-credit") { flushOnCredit(opened) }
        thread(isDaemon = true, name = "forward-udp-$localPort-in") { deliver(opened) }
    }

    private fun flushOnCredit(opened: ChannelStream) {
        if (!runBlocking { opened.awaitCredit() }) return
        synchronized(lock) {
            if (stream !== opened) return
            isCredited = true
            while (held.isNotEmpty()) opened.trySend(held.removeFirst())
        }
    }

    private fun deliver(opened: ChannelStream) {
        while (true) {
            val frame = runBlocking { opened.receive() } ?: break
            if (frame.size < CLIENT_UDP_SOURCE_BYTES) continue
            val source = ByteBuffer.wrap(frame, 0, CLIENT_UDP_SOURCE_BYTES).short.toInt() and 0xffff
            val target = synchronized(lock) { sources[source] } ?: continue
            try {
                socket?.send(
                    DatagramPacket(frame, CLIENT_UDP_SOURCE_BYTES, frame.size - CLIENT_UDP_SOURCE_BYTES, target),
                )
            } catch (error: IOException) {
                Log.i(CLIENT_LOG_TAG, "a datagram from $name was not delivered: ${error.message}")
            }
        }
        ended(opened)
    }

    private fun ended(opened: ChannelStream) {
        val (refusal, isEnding) = synchronized(lock) {
            if (stream !== opened || isClosed) return
            stream = null
            held.clear()
            val refusal = opened.refusal?.takeIf { it.code != "hub_unreachable" } ?: return
            refusedAt = clock()
            refusal to (isFirstStream && !hasSent)
        }
        Log.i(CLIENT_LOG_TAG, "the hub ended the stream to $name: ${refusal.code}")
        if (isEnding) close()
        onRefused(refusal, isEnding)
    }
}
