package io.github.iffix.neutrino.forward

import java.io.Closeable
import java.io.IOException
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import kotlin.concurrent.thread

/** A loopback server that writes back every byte it reads, standing in for a published port. */
class EchoServer : Closeable {
    private val server = ServerSocket(0, 50, InetAddress.getByName("127.0.0.1"))

    /** The port it answers on. */
    val port: Int = server.localPort

    init {
        thread(isDaemon = true) {
            while (true) {
                val client = try {
                    server.accept()
                } catch (_: IOException) {
                    break
                }
                thread(isDaemon = true) { echo(client) }
            }
        }
    }

    override fun close() = server.close()

    private fun echo(client: Socket) {
        client.use {
            val buffer = ByteArray(4096)
            try {
                while (true) {
                    val count = it.getInputStream().read(buffer)
                    if (count < 0) break
                    it.getOutputStream().write(buffer, 0, count)
                }
            } catch (_: IOException) {
                return
            }
        }
    }
}
