package io.github.iffix.neutrino.forward

import android.util.Log
import io.github.iffix.neutrino.CLIENT_HTTPS_DEFAULT_PORT
import io.github.iffix.neutrino.CLIENT_HTTP_DEFAULT_PORT
import io.github.iffix.neutrino.CLIENT_LOG_TAG
import io.github.iffix.neutrino.FORWARD_BIND_HOST
import io.github.iffix.neutrino.WEB_TOKEN_PARAMETER
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.HubView
import java.io.IOException
import java.net.URI
import java.net.URISyntaxException
import java.net.URLEncoder
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * The loopback forwards of the app core, by entry key `<binding>/<entry>`: a port entry's
 * Connect and Disconnect, and a local-only web entry's Open locally, which forwards, reads the
 * entry's token on the `service` stream and opens the browser on the loopback. A forward stops
 * when its hub is left, when its entry leaves the hub's state, and on [stopAll] as the app core's service ends.
 *
 * @param material What the hub hands this phone for one entry, by binding id and entry id.
 * @param scope Where the jobs run.
 * @param relayOf A relay to a published host and port, asking for a loopback number.
 */
class PortForwards(
    private val material: suspend (String, String) -> ChannelResult<JsonObject>,
    private val scope: CoroutineScope,
    private val relayOf: (String, Int, Int) -> PortForwardRelay = { host, port, local ->
        PortForwardRelay(host, port, local)
    },
) {
    private val current = MutableStateFlow<Map<String, PortForwardRow>>(emptyMap())
    private val relays = mutableMapOf<String, PortForwardRelay>()

    /** Every row with a forward, a job or an error, by entry key. */
    val rows: StateFlow<Map<String, PortForwardRow>> = current.asStateFlow()

    /**
     * Press Connect on a port entry. A press while the row's job runs is dropped.
     *
     * @param bindingId The hub.
     * @param entryId The entry.
     * @param host The address the published port answers on.
     * @param port The published port number.
     */
    fun connect(bindingId: String, entryId: String, host: String, port: Int) {
        val key = keyOf(bindingId, entryId)
        if (!begin(key, PortForwardJob.FORWARDING)) return
        scope.launch {
            when (val bound = forward(key, host, port)) {
                is ChannelResult.Refused -> settle(key) { PortForwardRow(error = bound) }
                is ChannelResult.Ok -> settle(key) { PortForwardRow(localPort = bound.value) }
            }
        }
    }

    /**
     * Press Disconnect on a forwarded entry. A press while the row's job runs is dropped.
     *
     * @param bindingId The hub.
     * @param entryId The entry.
     */
    fun disconnect(bindingId: String, entryId: String) {
        val key = keyOf(bindingId, entryId)
        if (!begin(key, PortForwardJob.DISCONNECTING)) return
        scope.launch {
            synchronized(relays) { relays.remove(key) }?.close()
            settle(key) { null }
        }
    }

    /**
     * Press Open locally on a local-only web entry: its address is forwarded to the loopback, its
     * token is read on the `service` stream, and the browser opens the loopback with the token.
     * A press while the row's job runs is dropped.
     *
     * @param bindingId The hub.
     * @param entryId The entry.
     * @param url The entry's address.
     * @param onOpen What opening the loopback address in the browser does.
     */
    fun openLocal(bindingId: String, entryId: String, url: String, onOpen: (String) -> Unit) {
        val key = keyOf(bindingId, entryId)
        if (!begin(key, PortForwardJob.OPENING)) return
        scope.launch {
            val target = targetOf(url)
            if (target == null) {
                settle(key) { it?.copy(job = null, error = UNREADABLE) ?: PortForwardRow(error = UNREADABLE) }
                return@launch
            }
            val (host, port, path) = target
            val bound = when (val forwarded = forward(key, host, port)) {
                is ChannelResult.Refused -> {
                    settle(key) { PortForwardRow(error = forwarded) }
                    return@launch
                }

                is ChannelResult.Ok -> forwarded.value
            }
            val token = when (val answer = material(bindingId, entryId)) {
                is ChannelResult.Refused -> {
                    settle(key) { PortForwardRow(localPort = bound, error = answer) }
                    return@launch
                }

                is ChannelResult.Ok -> (answer.value["token"] as? JsonPrimitive)?.content.orEmpty()
            }
            if (token.isEmpty()) {
                settle(key) { PortForwardRow(localPort = bound, error = ChannelResult.refused("web_token_missing")) }
                return@launch
            }
            val query = "$WEB_TOKEN_PARAMETER=${URLEncoder.encode(token, "UTF-8")}"
            onOpen("http://$FORWARD_BIND_HOST:$bound$path?$query")
            settle(key) { PortForwardRow(localPort = bound) }
        }
    }

    /**
     * Follow the hubs from now on: a forward whose hub serves this phone and no longer lists its
     * entry stops, and so does one whose hub is gone.
     *
     * @param hubs Every hub's view.
     */
    fun follow(hubs: Flow<List<HubView>>) {
        scope.launch { hubs.collect { take(it) } }
    }

    /**
     * Take one round of the hubs' state.
     *
     * @param hubs Every hub's view.
     */
    fun take(hubs: List<HubView>) {
        val byId = hubs.associateBy { it.binding.id }
        val gone = synchronized(relays) {
            relays.keys.filter { key ->
                val hub = byId[key.substringBefore('/')]
                hub == null || (hub.isConnected && hub.services.none { it.id == key.substringAfter('/') })
            }
        }
        for (key in gone) stop(key)
    }

    /**
     * A hub is being left: its forwards stop and its rows go.
     *
     * @param bindingId The hub.
     */
    fun forget(bindingId: String) {
        val keys = synchronized(relays) { relays.keys.filter { it.startsWith("$bindingId/") } }
        for (key in keys) stop(key)
        current.update { rows -> rows.filterKeys { !it.startsWith("$bindingId/") } }
    }

    /** Stop every forward, as when the app core's service ends. */
    fun stopAll() {
        val keys = synchronized(relays) { relays.keys.toList() }
        for (key in keys) stop(key)
    }

    /** A refresh: every row's error goes. */
    fun clearErrors() {
        current.update { rows ->
            rows.mapValues { (_, row) -> row.copy(error = null) }.filterValues { it != PortForwardRow() }
        }
    }

    private fun begin(key: String, job: PortForwardJob): Boolean {
        var isStarted = false
        current.update { rows ->
            val row = rows[key] ?: PortForwardRow()
            if (row.job != null) {
                rows
            } else {
                isStarted = true
                rows + (key to row.copy(job = job, error = null))
            }
        }
        if (!isStarted) Log.i(CLIENT_LOG_TAG, "a forward job runs on $key; the press is dropped")
        return isStarted
    }

    private fun forward(key: String, host: String, port: Int): ChannelResult<Int> {
        synchronized(relays) { relays[key]?.takeIf { it.isActive } }?.let { return ChannelResult.Ok(it.localPort) }
        val relay = relayOf(host, port, port)
        return try {
            val bound = relay.start()
            synchronized(relays) { relays.put(key, relay) }?.close()
            Log.i(CLIENT_LOG_TAG, "forwarding $FORWARD_BIND_HOST:$bound to $host:$port")
            ChannelResult.Ok(bound)
        } catch (error: IOException) {
            ChannelResult.refused("forward_failed", "detail" to (error.message ?: "IOException").take(200))
        }
    }

    private fun stop(key: String) {
        val relay = synchronized(relays) { relays.remove(key) } ?: return
        relay.close()
        Log.i(CLIENT_LOG_TAG, "stopped forwarding to ${relay.host}:${relay.port}")
        current.update { rows ->
            val row = rows[key] ?: return@update rows
            val left = row.copy(localPort = 0)
            if (left == PortForwardRow()) rows - key else rows + (key to left)
        }
    }

    private fun settle(key: String, next: (PortForwardRow?) -> PortForwardRow?) {
        current.update { rows ->
            when (val row = next(rows[key])) {
                null -> rows - key
                else -> rows + (key to row)
            }
        }
    }

    private fun targetOf(url: String): Triple<String, Int, String>? = try {
        val address = URI(url)
        val host = address.host
        val port = when {
            address.port > 0 -> address.port
            address.scheme == "https" -> CLIENT_HTTPS_DEFAULT_PORT
            else -> CLIENT_HTTP_DEFAULT_PORT
        }
        if (host.isNullOrEmpty()) null else Triple(host, port, address.rawPath.orEmpty().ifEmpty { "/" })
    } catch (_: URISyntaxException) {
        null
    }

    companion object {
        private val UNREADABLE = ChannelResult.refused("unknown_request")

        /**
         * The key of one entry.
         *
         * @param bindingId The hub.
         * @param entryId The entry.
         * @return `<binding>/<entry>`.
         */
        fun keyOf(bindingId: String, entryId: String): String = "$bindingId/$entryId"
    }
}
