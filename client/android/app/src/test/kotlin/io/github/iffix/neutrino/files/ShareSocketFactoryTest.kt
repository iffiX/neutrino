package io.github.iffix.neutrino.files

import java.net.InetAddress
import java.net.ServerSocket
import java.net.SocketTimeoutException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class ShareSocketFactoryTest {
    @Test
    fun theConnectAndTheReadAreBoundedApart() {
        val factory = ShareSocketFactory(connectTimeoutMillis = 5000, readTimeoutMillis = 60_000)
        assertEquals(60_000, factory.createSocket().soTimeout)
        assertEquals(5000, factory.connectTimeoutMillis)
    }

    @Test
    fun aSilentServerEndsAReadAtTheReadTimeoutNotTheConnectOne() {
        ServerSocket(0, 50, InetAddress.getByName("127.0.0.1")).use { server ->
            val factory = ShareSocketFactory(connectTimeoutMillis = 5000, readTimeoutMillis = 300)
            factory.createSocket("127.0.0.1", server.localPort).use { socket ->
                val started = System.nanoTime()
                try {
                    socket.getInputStream().read()
                    fail("the silent server answered")
                } catch (_: SocketTimeoutException) {
                    val waited = (System.nanoTime() - started) / 1_000_000
                    assertTrue("waited $waited ms", waited in 250..4000)
                }
            }
        }
    }

    @Test
    fun aServerThatIsNotThereFailsFast() {
        val closed = ServerSocket(0).use { it.localPort }
        val factory = ShareSocketFactory(connectTimeoutMillis = 5000, readTimeoutMillis = 60_000)
        val started = System.nanoTime()
        try {
            factory.createSocket("127.0.0.1", closed).close()
            fail("a closed port accepted")
        } catch (_: java.io.IOException) {
            assertTrue((System.nanoTime() - started) / 1_000_000 < 5000)
        }
    }
}
