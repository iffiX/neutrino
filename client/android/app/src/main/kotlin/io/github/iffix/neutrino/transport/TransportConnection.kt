package io.github.iffix.neutrino.transport

import java.io.Closeable
import java.io.InputStream
import java.io.OutputStream

/** One connection to the transport's local socket: its bytes both ways, closed by its owner. */
interface TransportConnection : Closeable {
    /** What the transport writes. */
    val input: InputStream

    /** What the app writes to the transport. */
    val output: OutputStream
}
