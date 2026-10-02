package io.github.iffix.neutrino.overlay

import io.github.iffix.neutrino.OVERLAY_PROBE_TIMEOUT_MILLIS
import java.io.IOException
import java.net.InetSocketAddress
import java.net.Socket
import java.net.URI
import java.net.URISyntaxException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** Whether the hub's port answers at one address, asked through whatever network the phone routes it by. */
object OverlayProbe {
    /**
     * Resolve the address's host and open one TCP connection to its port.
     *
     * @param url The hub's address, `https://host:port`.
     * @return Whether the connection opened within the timeout.
     */
    suspend fun isReachable(url: String): Boolean = withContext(Dispatchers.IO) {
        val target = try {
            URI(url)
        } catch (_: URISyntaxException) {
            return@withContext false
        }
        val host = target.host?.removePrefix("[")?.removeSuffix("]").orEmpty()
        if (host.isEmpty() || target.port <= 0) return@withContext false
        try {
            Socket().use { it.connect(InetSocketAddress(host, target.port), OVERLAY_PROBE_TIMEOUT_MILLIS) }
            true
        } catch (_: IOException) {
            false
        } catch (_: IllegalArgumentException) {
            false
        }
    }
}
