package io.github.iffix.neutrino.channel

import io.github.iffix.neutrino.ConnectRefusedException
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.net.Socket
import java.net.SocketAddress
import java.net.SocketException
import kotlinx.coroutines.runBlocking

/**
 * A socket whose bytes are one `connect` stream: connecting opens the stream, reading takes what
 * the hub relays and grants it credit as it is consumed, writing waits on the hub's credit, and
 * closing ends the stream. The address a caller connects to is not dialled; the stream's open
 * names its far end. A read waits until bytes come or the stream ends, whatever the read timeout
 * says. There is no half-close: shutting either direction closes the socket. A
 * stream the hub ends with a code ends a read or a write with [ConnectRefusedException].
 *
 * @param opener Opens the stream on the hub's socket.
 */
class ChannelConnectSocket(private val opener: () -> ChannelResult<ChannelStream>) : Socket() {
    private val input = StreamInput()
    private val output = StreamOutput()

    @Volatile
    private var stream: ChannelStream? = null

    @Volatile
    private var isShut = false

    private var readTimeoutMillis = 0

    /** The code the stream ended in: the hub's refusal, or `hub_unreachable` once its socket ended; else null. */
    val refusal: ChannelResult.Refused?
        get() = stream?.refusal

    /**
     * Open the stream.
     *
     * @throws ConnectRefusedException When the stream cannot be opened.
     * @throws SocketException When the socket is closed or already open.
     */
    fun open() {
        if (isShut) throw SocketException("the socket is closed")
        if (stream != null) throw SocketException("the socket is already connected")
        stream = when (val opened = opener()) {
            is ChannelResult.Refused -> throw ConnectRefusedException(opened.code, opened.params)
            is ChannelResult.Ok -> opened.value
        }
    }

    override fun connect(endpoint: SocketAddress?) = open()

    override fun connect(endpoint: SocketAddress?, timeout: Int) = open()

    override fun getInputStream(): InputStream {
        if (stream == null) throw SocketException("the socket is not connected")
        return input
    }

    override fun getOutputStream(): OutputStream {
        if (stream == null) throw SocketException("the socket is not connected")
        return output
    }

    override fun isConnected(): Boolean = stream != null

    override fun isClosed(): Boolean = isShut

    override fun isInputShutdown(): Boolean = isShut

    override fun isOutputShutdown(): Boolean = isShut

    override fun shutdownInput() = close()

    override fun shutdownOutput() = close()

    override fun setSoTimeout(timeout: Int) {
        readTimeoutMillis = timeout
    }

    override fun getSoTimeout(): Int = readTimeoutMillis

    override fun setTcpNoDelay(on: Boolean) = Unit

    override fun close() {
        isShut = true
        stream?.close()
    }

    override fun toString(): String = "ChannelConnectSocket(stream=${stream?.id})"

    private fun ended(stream: ChannelStream): IOException {
        val refusal = stream.refusal ?: return SocketException("the socket is closed")
        return ConnectRefusedException(refusal.code, refusal.params)
    }

    private inner class StreamInput : InputStream() {
        private var held = ByteArray(0)
        private var offset = 0

        override fun read(): Int {
            val one = ByteArray(1)
            return if (read(one, 0, 1) < 0) -1 else one[0].toInt() and 0xff
        }

        override fun read(buffer: ByteArray, at: Int, count: Int): Int {
            if (count == 0) return 0
            val current = stream ?: throw SocketException("the socket is not connected")
            if (offset >= held.size) {
                val next = runBlocking { current.read() }
                if (next == null) {
                    if (current.refusal != null) throw ended(current)
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

        override fun close() = this@ChannelConnectSocket.close()
    }

    private inner class StreamOutput : OutputStream() {
        override fun write(byte: Int) = write(byteArrayOf(byte.toByte()), 0, 1)

        override fun write(buffer: ByteArray, at: Int, count: Int) {
            if (count == 0) return
            val current = stream ?: throw SocketException("the socket is not connected")
            if (isShut) throw SocketException("the socket is closed")
            val sent = runBlocking { current.send(buffer.copyOfRange(at, at + count)) }
            if (sent is ChannelResult.Refused) throw ended(current)
        }

        override fun close() = this@ChannelConnectSocket.close()
    }
}
