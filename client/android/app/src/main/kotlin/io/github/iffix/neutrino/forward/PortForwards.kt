package io.github.iffix.neutrino.forward

import android.util.Log
import io.github.iffix.neutrino.CLIENT_HTTPS_DEFAULT_PORT
import io.github.iffix.neutrino.CLIENT_HTTP_DEFAULT_PORT
import io.github.iffix.neutrino.CLIENT_LOG_TAG
import io.github.iffix.neutrino.ConnectRefusedException
import io.github.iffix.neutrino.FORWARD_BIND_HOST
import io.github.iffix.neutrino.FORWARD_PANEL_ENTRY
import io.github.iffix.neutrino.FORWARD_PANEL_SLUG_PREFIX
import io.github.iffix.neutrino.LocalPortTakenException
import io.github.iffix.neutrino.PORT_PROTOCOL_TCP
import io.github.iffix.neutrino.PORT_PROTOCOL_UDP
import io.github.iffix.neutrino.WEB_LOOPBACK_DOMAIN
import io.github.iffix.neutrino.WEB_TOKEN_PARAMETER
import io.github.iffix.neutrino.channel.ChannelFrames
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.ChannelStream
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
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * The loopback forwards of the app core, by entry key `<binding>/<entry>`. Each forward listens
 * on `127.0.0.1` at the number the local port table gives its entry, and every connection it
 * accepts is one `connect` stream to the hub naming the entry. A port entry and the AI gateway
 * forward from Connect until Disconnect; a web entry from Open until Disconnect, its Open reading
 * the entry's token on the `service` stream when it needs one and opening the browser on the
 * entry's own `.localhost` name; a shared desktop from its Connect until its viewer closes; the
 * hub's panel, keyed `<binding>/#panel`, from the first press of Panel until the hub is left, each
 * press reading a one-time sign-in token first. A forward stops when its hub is left, when its
 * entry leaves the hub's state, and on [stopAll] as the app core's service ends.
 *
 * @param material What the hub hands this phone on a `service` stream, by binding id and the
 *   stream's arguments.
 * @param streams Opens one `connect` stream on a hub, by binding id and the stream's arguments.
 * @param scope Where the jobs run.
 * @param table The local port of every forwarded entry.
 * @param log Writes one line to the app's log: a forward made, a forward ended and why.
 * @param udpRelayOf A UDP entry's forward by what the log calls it, how it opens its stream, its
 *   loopback number, what a refusal of its stream does, with whether it ended the forward, and what
 *   a frame coming back after a refusal does.
 * @param relayOf A relay by what the log calls it, how it opens a stream, and its loopback number.
 */
class PortForwards(
    private val material: suspend (String, Map<String, JsonElement>) -> ChannelResult<JsonObject>,
    private val streams: (String, Map<String, JsonElement>) -> ChannelResult<ChannelStream>,
    private val scope: CoroutineScope,
    private val table: LocalPortTable,
    private val log: (String) -> Unit = { Log.i(CLIENT_LOG_TAG, it) },
    private val udpRelayOf: (
        String,
        () -> ChannelResult<ChannelStream>,
        Int,
        (ChannelResult.Refused, Boolean) -> Unit,
        () -> Unit,
    ) ->
    PortForwardListener = { name, open, local, onRefused, onAnswered ->
        PortForwardUdpRelay(name, open, local, onRefused, onAnswered)
    },
    private val relayOf: (String, () -> ChannelResult<ChannelStream>, Int) -> PortForwardRelay = { name, open, local ->
        PortForwardRelay(name, open, local)
    },
) {
    private val current = MutableStateFlow<Map<String, PortForwardRow>>(emptyMap())
    private val relays = mutableMapOf<String, PortForwardListener>()

    /** Every row with a forward, a job or an error, by entry key. */
    val rows: StateFlow<Map<String, PortForwardRow>> = current.asStateFlow()

    /**
     * Press Connect on a port entry or the AI gateway. A UDP entry's forward is one UDP socket and
     * one stream; a refusal of its stream that ends it, or a later one, is the row's error. A
     * press while the row's job runs is dropped.
     *
     * @param bindingId The hub.
     * @param entryId The entry.
     * @param port The entry's own port, which the local port table tries first.
     * @param protocol `tcp` or `udp`.
     */
    fun connect(bindingId: String, entryId: String, port: Int, protocol: String = PORT_PROTOCOL_TCP) {
        val key = keyOf(bindingId, entryId)
        if (!begin(key, PortForwardJob.FORWARDING)) return
        scope.launch {
            when (val bound = forward(key, bindingId, entryArgs(entryId), port, protocol)) {
                is ChannelResult.Refused -> settle(key) { PortForwardRow(error = bound) }

                is ChannelResult.Ok -> settle(key) { row ->
                    val isListening = synchronized(relays) { relays[key]?.isActive == true }
                    if (isListening) PortForwardRow(localPort = bound.value) else row?.copy(job = null, localPort = 0)
                }
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
            stop(key, "the person disconnected")
            settle(key) { null }
        }
    }

    /**
     * Press Open on a web entry: its forward is made when it has none, a fresh token is read on
     * the `service` stream when the entry needs one, and the browser opens
     * `<scheme>://<slug>.localhost:<local port><path>`, with `?tkn=<token>` for a token entry,
     * where the slug is the entry's id with every character outside letters, digits and hyphens
     * turned into a hyphen. A press while the row's job runs is dropped.
     *
     * @param bindingId The hub.
     * @param entryId The entry.
     * @param url The entry's address, where it stands on the hub's networks.
     * @param isTokenRequired Whether the page opens with a token.
     * @param onOpen What opening the loopback address in the browser does.
     */
    fun open(bindingId: String, entryId: String, url: String, isTokenRequired: Boolean, onOpen: (String) -> Unit) {
        val key = keyOf(bindingId, entryId)
        if (!begin(key, PortForwardJob.OPENING)) return
        scope.launch {
            val target = targetOf(url)
            if (target == null) {
                settle(key) { it?.copy(job = null, error = UNREADABLE) ?: PortForwardRow(error = UNREADABLE) }
                return@launch
            }
            val bound = when (val forwarded = forward(key, bindingId, entryArgs(entryId), target.port)) {
                is ChannelResult.Refused -> {
                    settle(key) { PortForwardRow(error = forwarded) }
                    return@launch
                }

                is ChannelResult.Ok -> forwarded.value
            }
            val address = "${target.scheme}://${slugOf(entryId)}.$WEB_LOOPBACK_DOMAIN:$bound${target.path}"
            if (!isTokenRequired) {
                onOpen(address)
                settle(key) { PortForwardRow(localPort = bound) }
                return@launch
            }
            val token = when (val answer = material(bindingId, entryArgs(entryId))) {
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
            onOpen(tokenUrlOf(address, token))
            settle(key) { PortForwardRow(localPort = bound) }
        }
    }

    /**
     * Press Panel on a hub's row: a one-time `{token}` is read on a `service` stream with
     * `{is_panel: true}`, the panel's forward is made when the hub has none, and the browser opens
     * `http://panel-<hub id>.localhost:<local port>/?tkn=<token>`, which signs the panel in. A
     * refusal of either is the row's error and opens nothing. The token goes to the browser and
     * is kept nowhere else. A press while the job runs is dropped.
     *
     * @param bindingId The hub.
     * @param hubId The hub's own id, from its welcome.
     * @param onOpen What opening the loopback address in the browser does.
     */
    fun openPanel(bindingId: String, hubId: String, onOpen: (String) -> Unit) {
        val key = keyOf(bindingId, FORWARD_PANEL_ENTRY)
        if (!begin(key, PortForwardJob.OPENING)) return
        scope.launch {
            val args = ChannelFrames.args("is_panel" to true)
            val token = when (val answer = material(bindingId, args)) {
                is ChannelResult.Refused -> {
                    settle(key) { it?.copy(job = null, error = answer) ?: PortForwardRow(error = answer) }
                    return@launch
                }

                is ChannelResult.Ok -> (answer.value["token"] as? JsonPrimitive)?.content.orEmpty()
            }
            if (token.isEmpty()) {
                val missing = ChannelResult.refused("web_token_missing")
                settle(key) { it?.copy(job = null, error = missing) ?: PortForwardRow(error = missing) }
                return@launch
            }
            when (val bound = forward(key, bindingId, args, 0)) {
                is ChannelResult.Refused -> settle(key) { PortForwardRow(error = bound) }

                is ChannelResult.Ok -> {
                    onOpen(tokenUrlOf("http://${panelHostOf(hubId.ifEmpty { bindingId })}:${bound.value}/", token))
                    settle(key) { PortForwardRow(localPort = bound.value) }
                }
            }
        }
    }

    /**
     * Make an entry's forward for a job of another page, such as a shared desktop's Connect; it
     * shows on no row and ends with [release].
     *
     * @param bindingId The hub.
     * @param entryId The entry.
     * @param port The entry's own port, which the local port table tries first.
     * @return The loopback number, `port_taken {port}` when another program listens on the fixed number,
     *   or `forward_failed`.
     */
    fun hold(bindingId: String, entryId: String, port: Int): ChannelResult<Int> =
        forward(keyOf(bindingId, entryId), bindingId, entryArgs(entryId), port)

    /**
     * End a forward [hold] made.
     *
     * @param bindingId The hub.
     * @param entryId The entry.
     */
    fun release(bindingId: String, entryId: String) = stop(keyOf(bindingId, entryId), "its viewer closed")

    /**
     * One entry's local port, as the Configure dialog opens on it.
     *
     * @param bindingId The hub.
     * @param entryId The entry.
     * @return Automatic or fixed, with the number held.
     */
    fun localPortOf(bindingId: String, entryId: String): LocalPortChoice = table.choiceOf(keyOf(bindingId, entryId))

    /**
     * Save the Configure dialog: one entry's local port, while the entry is not forwarded.
     *
     * @param bindingId The hub.
     * @param entryId The entry.
     * @param choice Automatic, or fixed with a number from 1024 to 65535.
     * @param protocol The entry's protocol, `tcp` or `udp`.
     * @return Ok once kept; `disconnect_first` while the entry is forwarded; `port_taken {port}`
     *   when another entry of the same protocol holds the fixed number.
     * @throws IllegalArgumentException When a fixed number is outside 1024 to 65535.
     */
    fun configure(
        bindingId: String,
        entryId: String,
        choice: LocalPortChoice,
        protocol: String = PORT_PROTOCOL_TCP,
    ): ChannelResult<Unit> {
        val key = keyOf(bindingId, entryId)
        if (synchronized(relays) { relays[key]?.isActive == true }) return ChannelResult.refused("disconnect_first")
        return table.configure(key, choice, protocol)
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
     * Take one round of the hubs' state: a forward stops when its hub is gone, or when its hub
     * serves this phone and no longer lists its entry; the panel's when its hub no longer lets
     * this phone open the panel.
     *
     * @param hubs Every hub's view.
     */
    fun take(hubs: List<HubView>) {
        val byId = hubs.associateBy { it.binding.id }
        val gone = synchronized(relays) {
            relays.keys.mapNotNull { key ->
                val hub = byId[key.substringBefore('/')]
                val entryId = key.substringAfter('/')
                when {
                    hub == null -> key to "the hub was left"

                    !hub.isConnected -> null

                    entryId == FORWARD_PANEL_ENTRY -> (key to "the hub took the panel away").takeIf {
                        !hub.isPanelAllowed
                    }

                    else -> (key to "the hub withdrew the entry").takeIf { hub.services.none { it.id == entryId } }
                }
            }
        }
        for ((key, why) in gone) stop(key, why)
    }

    /**
     * A hub is being left: its forwards stop and its rows go.
     *
     * @param bindingId The hub.
     */
    fun forget(bindingId: String) {
        val keys = synchronized(relays) { relays.keys.filter { it.startsWith("$bindingId/") } }
        for (key in keys) stop(key, "the hub was left")
        current.update { rows -> rows.filterKeys { !it.startsWith("$bindingId/") } }
        table.forget(bindingId)
    }

    /** Stop every forward, as when the app core's service ends. */
    fun stopAll() {
        val keys = synchronized(relays) { relays.keys.toList() }
        for (key in keys) stop(key, "the app core stopped")
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
        if (!isStarted) log("a forward job runs on $key; the press is dropped")
        return isStarted
    }

    private fun forward(
        key: String,
        bindingId: String,
        args: Map<String, JsonElement>,
        port: Int,
        protocol: String = PORT_PROTOCOL_TCP,
    ): ChannelResult<Int> {
        synchronized(relays) { relays[key]?.takeIf { it.isActive } }?.let { return ChannelResult.Ok(it.localPort) }
        return try {
            val local = table.portFor(key, port, protocol)
            val open = { streams(bindingId, args) }
            val relay = if (protocol == PORT_PROTOCOL_UDP) {
                udpRelayOf(key, open, local, { refusal, isEnded -> refused(key, refusal, isEnded) }) {
                    settle(key) { it?.copy(error = null) }
                }
            } else {
                relayOf(key, open, local)
            }
            synchronized(relays) { relays.put(key, relay) }?.close()
            val bound = try {
                relay.start()
            } catch (error: IOException) {
                synchronized(relays) { if (relays[key] === relay) relays.remove(key) }
                throw error
            }
            if (relay.isActive) log("forwarding $FORWARD_BIND_HOST:$bound to $key through the hub")
            ChannelResult.Ok(bound)
        } catch (error: LocalPortTakenException) {
            ChannelResult.refused("port_taken", "port" to error.port.toString())
        } catch (error: ConnectRefusedException) {
            ChannelResult.Refused(error.code, error.params)
        } catch (error: IOException) {
            ChannelResult.refused("forward_failed", "detail" to (error.message ?: "IOException").take(200))
        }
    }

    private fun stop(key: String, why: String) {
        val relay = synchronized(relays) { relays.remove(key) } ?: return
        relay.close()
        logStopped(relay, why)
        current.update { rows ->
            val row = rows[key] ?: return@update rows
            val left = row.copy(localPort = 0)
            if (left == PortForwardRow()) rows - key else rows + (key to left)
        }
    }

    private fun refused(key: String, refusal: ChannelResult.Refused, isEnded: Boolean) {
        if (isEnded) {
            synchronized(relays) { relays.remove(key) }?.let { logStopped(it, "the hub refused it: ${refusal.code}") }
        }
        settle(key) { row ->
            val kept = row ?: PortForwardRow()
            if (isEnded) kept.copy(localPort = 0, error = refusal) else kept.copy(error = refusal)
        }
    }

    private fun logStopped(relay: PortForwardListener, why: String) =
        log("stopped forwarding $FORWARD_BIND_HOST:${relay.localPort} to ${relay.name}: $why")

    private fun settle(key: String, next: (PortForwardRow?) -> PortForwardRow?) {
        current.update { rows ->
            when (val row = next(rows[key])) {
                null -> rows - key
                else -> rows + (key to row)
            }
        }
    }

    private fun entryArgs(entryId: String): Map<String, JsonElement> = ChannelFrames.args("id" to entryId)

    private fun targetOf(url: String): WebTarget? = try {
        val address = URI(url)
        val scheme = address.scheme?.lowercase().orEmpty()
        val port = when {
            address.port > 0 -> address.port
            scheme == "https" -> CLIENT_HTTPS_DEFAULT_PORT
            else -> CLIENT_HTTP_DEFAULT_PORT
        }
        if (scheme.isEmpty() || address.host.isNullOrEmpty()) {
            null
        } else {
            WebTarget(scheme, port, address.rawPath.orEmpty().ifEmpty { "/" })
        }
    } catch (_: URISyntaxException) {
        null
    }

    private class WebTarget(val scheme: String, val port: Int, val path: String)

    companion object {
        private val UNREADABLE = ChannelResult.refused("unknown_request")
        private val SLUG_OUTSIDE = Regex("[^A-Za-z0-9-]")

        /**
         * The host label an entry's page is opened under.
         *
         * @param entryId The entry's id.
         * @return The id with every character outside letters, digits and hyphens turned into a hyphen.
         */
        fun slugOf(entryId: String): String = entryId.replace(SLUG_OUTSIDE, "-")

        /**
         * The host a hub's panel is opened under, so each hub's panel keeps its own cookie.
         *
         * @param hubId The hub's id.
         * @return `panel-<slug of the id>.localhost`.
         */
        fun panelHostOf(hubId: String): String = "$FORWARD_PANEL_SLUG_PREFIX${slugOf(hubId)}.$WEB_LOOPBACK_DOMAIN"

        /**
         * The key of one entry.
         *
         * @param bindingId The hub.
         * @param entryId The entry.
         * @return `<binding>/<entry>`.
         */
        fun keyOf(bindingId: String, entryId: String): String = "$bindingId/$entryId"

        /**
         * The key of a hub's panel forward.
         *
         * @param bindingId The hub.
         * @return `<binding>/#panel`.
         */
        fun panelKeyOf(bindingId: String): String = keyOf(bindingId, FORWARD_PANEL_ENTRY)

        /**
         * An address with the token it opens with.
         *
         * @param url The address.
         * @param token The token the hub handed for this open.
         * @return The address with `tkn=<token>` added to its query.
         */
        fun tokenUrlOf(url: String, token: String): String {
            val query = "$WEB_TOKEN_PARAMETER=${URLEncoder.encode(token, "UTF-8")}"
            return if ('?' in url) "$url&$query" else "$url?$query"
        }
    }
}
