package io.github.iffix.neutrino.files

import io.github.iffix.neutrino.channel.ChannelConnectSocket
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.ChannelStream
import java.net.InetAddress
import java.net.Socket
import javax.net.SocketFactory

/**
 * The sockets one share is reached over: each is a `connect` stream to the hub naming the share's
 * `file` entry, whatever host and port the SMB library asks for, so no connection dials the
 * share's own address.
 *
 * @param opener Opens one `connect` stream for the share.
 */
class ShareSocketFactory(private val opener: () -> ChannelResult<ChannelStream>) : SocketFactory() {
    private val made = mutableListOf<ChannelConnectSocket>()

    /** The code the first of its streams the hub ended ended in, or null while none was. */
    val refusal: ChannelResult.Refused?
        get() = synchronized(made) { made.firstNotNullOfOrNull { it.refusal } }

    override fun createSocket(): Socket = socket()

    override fun createSocket(host: String, port: Int): Socket = socket().also { it.open() }

    override fun createSocket(host: String, port: Int, localHost: InetAddress, localPort: Int): Socket =
        createSocket(host, port)

    override fun createSocket(host: InetAddress, port: Int): Socket = socket().also { it.open() }

    override fun createSocket(address: InetAddress, port: Int, localAddress: InetAddress, localPort: Int): Socket =
        createSocket(address, port)

    private fun socket(): ChannelConnectSocket = ChannelConnectSocket(opener).also { synchronized(made) { made += it } }
}
