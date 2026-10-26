package io.github.iffix.neutrino.channel

import io.github.iffix.neutrino.ConnectRefusedException
import io.github.iffix.neutrino.transport.TransportStream
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.net.Socket
import java.net.SocketAddress
import java.net.SocketException

/**
 * A socket whose bytes are one `connect` stream: connecting opens the stream on the hub's session
 * through the transport, and after the hub's `accept` the stream carries the connection's raw
 * bytes both ways. The address a caller connects to is not dialled; the stream's open names its
 * far end. There is no half-close: shutting either direction closes the socket. A stream the hub
 * refuses ends the connect with [ConnectRefusedException].
 *
 * @param opener Opens the stream on the hub's session.
 */
class ChannelConnectSocket(private val opener: () -> ChannelResult<TransportStream>) : Socket() {
    @Volatile
    private var stream: TransportStream? = null

    @Volatile
    private var isShut = false

    @Volatile
    private var refused: ChannelResult.Refused? = null

    private var readTimeoutMillis = 0

    /** The code the stream's open was refused with, or null. */
    val refusal: ChannelResult.Refused?
        get() = refused

    /**
     * Open the stream.
     *
     * @throws ConnectRefusedException When the hub or the transport refuses the stream.
     * @throws SocketException When the socket is closed or already open.
     */
    fun open() {
        if (isShut) throw SocketException("the socket is closed")
        if (stream != null) throw SocketException("the socket is already connected")
        stream = when (val opened = opener()) {
            is ChannelResult.Refused -> {
                refused = opened
                throw ConnectRefusedException(opened.code, opened.params)
            }

            is ChannelResult.Ok -> opened.value
        }
    }

    override fun connect(endpoint: SocketAddress?) = open()

    override fun connect(endpoint: SocketAddress?, timeout: Int) = open()

    override fun getInputStream(): InputStream {
        val open = stream ?: throw SocketException("the socket is not connected")
        return Input(open.rawInput)
    }

    override fun getOutputStream(): OutputStream {
        val open = stream ?: throw SocketException("the socket is not connected")
        return Output(open.rawOutput)
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

    override fun toString(): String = "ChannelConnectSocket(open=${stream != null}, closed=$isShut)"

    private inner class Input(private val source: InputStream) : InputStream() {
        override fun read(): Int {
            val one = ByteArray(1)
            return if (read(one, 0, 1) < 0) -1 else one[0].toInt() and 0xff
        }

        override fun read(buffer: ByteArray, at: Int, count: Int): Int {
            if (isShut) throw SocketException("the socket is closed")
            return try {
                source.read(buffer, at, count)
            } catch (error: IOException) {
                if (isShut) throw SocketException("the socket is closed")
                throw error
            }
        }

        override fun available(): Int = source.available()

        override fun close() = this@ChannelConnectSocket.close()
    }

    private inner class Output(private val sink: OutputStream) : OutputStream() {
        override fun write(byte: Int) = write(byteArrayOf(byte.toByte()), 0, 1)

        override fun write(buffer: ByteArray, at: Int, count: Int) {
            if (isShut) throw SocketException("the socket is closed")
            sink.write(buffer, at, count)
        }

        override fun flush() = sink.flush()

        override fun close() = this@ChannelConnectSocket.close()
    }
}
