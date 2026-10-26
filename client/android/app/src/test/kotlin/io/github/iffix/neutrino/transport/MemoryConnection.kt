package io.github.iffix.neutrino.transport

import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

/**
 * One end of an in-memory duplex connection, as a local socket's would be: what one end writes
 * the other reads, and closing either end ends both directions.
 */
class MemoryConnection private constructor(
    private val inbox: LinkedBlockingQueue<ByteArray>,
    private val outbox: LinkedBlockingQueue<ByteArray>,
) : TransportConnection {
    @Volatile
    private var isClosed = false

    @Volatile
    private var isWaiting = false

    /** Whether the reader of this end has taken everything written to it and waits for more. */
    val isDrained: Boolean
        get() = isWaiting && inbox.isEmpty()

    private var peer: MemoryConnection? = null

    /** The other end of the connection. */
    val other: MemoryConnection?
        get() = peer

    override val input: InputStream = object : InputStream() {
        private var held = ByteArray(0)
        private var offset = 0

        override fun read(): Int {
            val one = ByteArray(1)
            return if (read(one, 0, 1) < 0) -1 else one[0].toInt() and 0xff
        }

        override fun read(buffer: ByteArray, at: Int, count: Int): Int {
            if (count == 0) return 0
            while (offset >= held.size) {
                if (isClosed && inbox.isEmpty()) return -1
                isWaiting = true
                val next = inbox.poll(POLL_MILLIS, TimeUnit.MILLISECONDS) ?: continue
                isWaiting = false
                if (next.isEmpty()) {
                    isClosed = true
                    return -1
                }
                held = next
                offset = 0
            }
            val size = minOf(count, held.size - offset)
            System.arraycopy(held, offset, buffer, at, size)
            offset += size
            return size
        }

        override fun available(): Int = held.size - offset
    }

    override val output: OutputStream = object : OutputStream() {
        override fun write(byte: Int) = write(byteArrayOf(byte.toByte()), 0, 1)

        override fun write(buffer: ByteArray, at: Int, count: Int) {
            if (isClosed || peer?.isClosed == true) throw IOException("the connection is closed")
            if (count > 0) outbox.put(buffer.copyOfRange(at, at + count))
        }
    }

    override fun close() {
        if (isClosed) return
        isClosed = true
        outbox.put(ByteArray(0))
        inbox.put(ByteArray(0))
    }

    companion object {
        private const val POLL_MILLIS = 50L

        /**
         * Two connected ends.
         *
         * @return The app's end and the transport's end.
         */
        fun pair(): Pair<MemoryConnection, MemoryConnection> {
            val toTransport = LinkedBlockingQueue<ByteArray>()
            val toApp = LinkedBlockingQueue<ByteArray>()
            val app = MemoryConnection(toApp, toTransport)
            val transport = MemoryConnection(toTransport, toApp)
            app.peer = transport
            transport.peer = app
            return app to transport
        }
    }
}
