package io.github.iffix.neutrino.forward

import android.util.Log
import io.github.iffix.neutrino.CLIENT_LOG_TAG
import io.github.iffix.neutrino.FORWARD_BIND_HOST
import io.github.iffix.neutrino.FORWARD_PANEL_ENTRY
import io.github.iffix.neutrino.FORWARD_PANEL_SLUG_PREFIX
import io.github.iffix.neutrino.FORWARD_PROTOCOL_UDP
import io.github.iffix.neutrino.FORWARD_UDP_RESTART_MILLIS
import io.github.iffix.neutrino.LocalPortTakenException
import io.github.iffix.neutrino.WEB_LOOPBACK_DOMAIN
import io.github.iffix.neutrino.WEB_TOKEN_PARAMETER
import io.github.iffix.neutrino.channel.ChannelApp
import io.github.iffix.neutrino.channel.ChannelFrames
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.ChannelServiceEntry
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.transport.TransportForwardEnd
import java.io.IOException
import java.net.URI
import java.net.URISyntaxException
import java.net.URLEncoder
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * The loopback forwards of the app core, held by the transport. An app's Use forwards each of its
 * `web` and `port` entries at its local port, the person's number or the hub's, and opens the
 * browser at the app's first `http` or `https` entry, with a fresh token for an entry that takes
 * one; the app is in use until Stop, its hub's leave or the app's quit. A shared desktop's forward
 * lives from its Connect until its viewer closes, and the hub's panel's from the first press of
 * Panel until the hub is left, each on a number picked from 20000 to 23999 and kept. A forward
 * stops when its hub is left and when its entry leaves the hub's state. A UDP forward the hub
 * closed with a code is started again a second later while its app is in use.
 *
 * @param material What the hub hands this phone on a `service` frame, by binding id and the frame's arguments.
 * @param forwarder Holds the listeners.
 * @param scope Where the jobs run.
 * @param table The local port of every forwarded entry.
 * @param loopbackHost The host every app opens under, or null to open each under its own local name.
 * @param log Writes one line to the app's log: a forward made, a forward ended and why.
 */
class PortForwards(
    private val material: suspend (String, Map<String, JsonElement>) -> ChannelResult<JsonObject>,
    private val forwarder: LocalForwarder,
    private val scope: CoroutineScope,
    private val table: LocalPortTable,
    private val loopbackHost: String? = null,
    private val log: (String) -> Unit = { Log.i(CLIENT_LOG_TAG, it) },
) {
    private val current = MutableStateFlow<Map<String, PortForwardRow>>(emptyMap())
    private val listening = MutableStateFlow<Map<String, Listener>>(emptyMap())
    private val lock = Any()

    /** Every app's and panel's row with a forward, a job or an error, by key `<binding>/<app>`. */
    val rows: StateFlow<Map<String, PortForwardRow>> = current.asStateFlow()

    /**
     * Press Use on an app: every entry's forward it has not got, then the browser at its first
     * `http` or `https` entry, in the hub's order, with a fresh token where that entry takes one.
     * A failure writes its code on the row, and the forwards that started stay up. A press while
     * the row's job runs is dropped.
     *
     * @param hub The hub that publishes the app.
     * @param app The app.
     * @param onOpen What opening an address in the browser does.
     */
    fun use(hub: HubView, app: ChannelApp, onOpen: (String) -> Unit) {
        val bindingId = hub.binding.id
        val key = keyOf(bindingId, app.id)
        if (!begin(key, PortForwardJob.OPENING)) return
        scope.launch {
            val entries = entriesOf(hub, app)
            var failure: ChannelResult.Refused? = null
            for (entry in entries) {
                val made = forward(bindingId, entry)
                if (made is ChannelResult.Refused && failure == null) failure = made
            }
            val isAny = entries.any { keyOf(bindingId, it.id) in listening.value }
            val page = entries.firstOrNull { it.type == "web" && targetOf(it.text("url")) != null }
            val error = failure ?: page?.let { open(hub, app, it, onOpen) }
            settle(key) { it.copy(isInUse = it.isInUse || isAny, job = null, error = error) }
        }
    }

    /**
     * Press Stop on an app: every forward of the app ends. A press while the row's job runs is dropped.
     *
     * @param bindingId The hub.
     * @param appId The app.
     */
    fun stop(bindingId: String, appId: String) {
        val key = keyOf(bindingId, appId)
        if (!begin(key, PortForwardJob.DISCONNECTING)) return
        scope.launch {
            val gone = listening.value.filterValues { it.appKey == key }.keys
            for (entryKey in gone) end(entryKey, "the person stopped the app")
            settle(key) { it.copy(isInUse = false, job = null) }
        }
    }

    /**
     * The numbers the person set for an app's entries, as its Configure dialog opens on them.
     *
     * @param bindingId The hub.
     * @param entries The app's entries.
     * @return Each entry's number, by entry id, null where it takes the hub's.
     */
    fun numbersOf(bindingId: String, entries: List<ChannelServiceEntry>): Map<String, Int?> =
        entries.associate { it.id to table.numberOf(keyOf(bindingId, it.id)) }

    /**
     * The number an app entry listens on: the person's, else the hub's.
     *
     * @param bindingId The hub.
     * @param entry The entry.
     * @return The number.
     */
    fun portOf(bindingId: String, entry: ChannelServiceEntry): Int =
        table.portOf(keyOf(bindingId, entry.id), entry.localPort)

    /**
     * Save an app's Configure dialog, while the app is not in use.
     *
     * @param hubs Every hub, for the hub numbers a number may not take.
     * @param bindingId The hub.
     * @param appId The app.
     * @param numbers Each entry's number by entry id, null to go back to the hub's.
     * @return Ok once kept; `disconnect_first` while the app is in use; `port_taken {port}` when
     *   another entry of the protocol holds a number.
     * @throws IllegalArgumentException When a number is outside 1024 to 65535.
     */
    fun configure(
        hubs: List<HubView>,
        bindingId: String,
        appId: String,
        numbers: Map<String, Int?>,
    ): ChannelResult<Unit> {
        if (current.value[keyOf(bindingId, appId)]?.isInUse == true) return ChannelResult.refused("disconnect_first")
        val hubNumbers = hubs.flatMap { hub ->
            hub.services.filter { it.localPort > 0 }.map {
                keyOf(hub.binding.id, it.id) to (it.localPort to it.protocol)
            }
        }.toMap()
        val hub = hubs.firstOrNull { it.binding.id == bindingId } ?: return ChannelResult.Ok(Unit)
        for ((entryId, number) in numbers) {
            val entry = hub.services.firstOrNull { it.id == entryId && it.appId == appId } ?: continue
            val kept = table.configure(keyOf(bindingId, entryId), number, entry.protocol, hubNumbers)
            if (kept is ChannelResult.Refused) return kept
        }
        return ChannelResult.Ok(Unit)
    }

    /**
     * Press Panel on a hub's row: a one-time `{token}` is read on a `service` frame with
     * `{is_panel: true}`, the panel's forward is made when the hub has none, and the browser opens
     * `http://panel-<hub id>.localhost:<local port>/?tkn=<token>`, which signs the panel in. A
     * refusal of either is the row's error and opens nothing. A press while the job runs is dropped.
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
                    settle(key) { it.copy(job = null, error = answer) }
                    return@launch
                }

                is ChannelResult.Ok -> (answer.value["token"] as? JsonPrimitive)?.content.orEmpty()
            }
            if (token.isEmpty()) {
                settle(key) { it.copy(job = null, error = ChannelResult.refused("web_token_missing")) }
                return@launch
            }
            when (val bound = pick(bindingId, FORWARD_PANEL_ENTRY, key, buildJsonObject { put("is_panel", true) })) {
                is ChannelResult.Refused -> settle(key) { it.copy(job = null, error = bound) }

                is ChannelResult.Ok -> {
                    val host = loopbackHost ?: panelHostOf(hubId.ifEmpty { bindingId })
                    onOpen(tokenUrlOf("http://$host:${bound.value}/", token))
                    settle(key) { it.copy(localPort = bound.value, job = null, error = null) }
                }
            }
        }
    }

    /**
     * Make an entry's forward for a job of another page, such as a shared desktop's Connect, on a
     * number picked from 20000 to 23999; it shows on no row and ends with [release].
     *
     * @param bindingId The hub.
     * @param entryId The entry.
     * @return The loopback number, or the refusal.
     */
    suspend fun hold(bindingId: String, entryId: String): ChannelResult<Int> =
        pick(bindingId, entryId, "", entryOpen(entryId))

    /**
     * End a forward [hold] made.
     *
     * @param bindingId The hub.
     * @param entryId The entry.
     */
    fun release(bindingId: String, entryId: String) {
        scope.launch { end(keyOf(bindingId, entryId), "its viewer closed") }
    }

    /**
     * Follow the hubs and the transport's ended listeners from now on.
     *
     * @param hubs Every hub's view.
     * @param ends The listeners the transport ended.
     */
    fun follow(hubs: Flow<List<HubView>>, ends: Flow<TransportForwardEnd>) {
        scope.launch { hubs.collect { take(it) } }
        scope.launch { ends.collect { ended(it) } }
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
        val gone = listening.value.keys.mapNotNull { entryKey ->
            val hub = byId[entryKey.substringBefore('/')]
            val entryId = entryKey.substringAfter('/')
            when {
                hub == null -> entryKey to "the hub was left"

                !hub.isConnected -> null

                entryId == FORWARD_PANEL_ENTRY -> (entryKey to "the hub took the panel away").takeIf {
                    !hub.isPanelAllowed
                }

                else -> (entryKey to "the hub withdrew the entry").takeIf { hub.services.none { it.id == entryId } }
            }
        }
        if (gone.isEmpty()) return
        scope.launch { for ((entryKey, why) in gone) end(entryKey, why) }
    }

    /**
     * A hub is being left: its forwards stop and its rows go.
     *
     * @param bindingId The hub.
     */
    fun forget(bindingId: String) {
        val keys = listening.value.keys.filter { it.startsWith("$bindingId/") }
        scope.launch { for (key in keys) end(key, "the hub was left") }
        current.update { rows -> rows.filterKeys { !it.startsWith("$bindingId/") } }
        table.forget(bindingId)
    }

    /** Stop every forward, as when the app core's service ends. */
    fun stopAll() {
        val keys = listening.value.keys.toList()
        scope.launch { for (key in keys) end(key, "the app core stopped") }
        current.update { rows -> rows.mapValues { (_, row) -> row.copy(isInUse = false, localPort = 0) } }
    }

    /** A refresh: every row's error goes. */
    fun clearErrors() {
        current.update { rows ->
            rows.mapValues { (_, row) -> row.copy(error = null) }.filterValues { it != PortForwardRow() }
        }
    }

    private suspend fun open(
        hub: HubView,
        app: ChannelApp,
        entry: ChannelServiceEntry,
        onOpen: (String) -> Unit,
    ): ChannelResult.Refused? {
        val bindingId = hub.binding.id
        val port = listening.value[keyOf(bindingId, entry.id)]?.port ?: return null
        val target = targetOf(entry.text("url")) ?: return null
        val host = loopbackHost ?: app.localName.ifEmpty { FORWARD_BIND_HOST }
        val address = "${target.first}://$host:$port${target.second}"
        if (!entry.flag("is_token_required")) {
            onOpen(address)
            return null
        }
        val token = when (val answer = material(bindingId, ChannelFrames.args("id" to entry.id))) {
            is ChannelResult.Refused -> return answer
            is ChannelResult.Ok -> (answer.value["token"] as? JsonPrimitive)?.content.orEmpty()
        }
        if (token.isEmpty()) return ChannelResult.refused("web_token_missing")
        onOpen(tokenUrlOf(address, token))
        return null
    }

    private suspend fun forward(bindingId: String, entry: ChannelServiceEntry): ChannelResult<Int> {
        val entryKey = keyOf(bindingId, entry.id)
        listening.value[entryKey]?.let { return ChannelResult.Ok(it.port) }
        val protocol = entry.protocol
        val port = try {
            if (entry.localPort <= 0 && table.numberOf(entryKey) == null) {
                table.pickFor(entryKey, protocol)
            } else {
                table.portForEntry(entryKey, entry.localPort, protocol)
            }
        } catch (error: LocalPortTakenException) {
            return ChannelResult.refused("port_taken", "port" to error.port.toString())
        } catch (error: IOException) {
            return ChannelResult.refused("forward_failed", "detail" to (error.message ?: "IOException"))
        }
        val isHeld = listening.value.values.any { it.port == port && it.protocol == protocol }
        if (isHeld) return ChannelResult.refused("port_taken", "port" to port.toString())
        val appKey = keyOf(bindingId, entry.appId)
        return listen(bindingId, entryKey, appKey, port, protocol, entryOpen(entry.id))
    }

    private suspend fun pick(bindingId: String, entryId: String, rowKey: String, open: JsonObject): ChannelResult<Int> {
        val entryKey = keyOf(bindingId, entryId)
        listening.value[entryKey]?.let { return ChannelResult.Ok(it.port) }
        val port = try {
            table.pickFor(entryKey, "tcp")
        } catch (error: IOException) {
            return ChannelResult.refused("forward_failed", "detail" to (error.message ?: "IOException"))
        }
        return listen(bindingId, entryKey, rowKey, port, "tcp", open)
    }

    private suspend fun listen(
        bindingId: String,
        entryKey: String,
        appKey: String,
        port: Int,
        protocol: String,
        open: JsonObject,
    ): ChannelResult<Int> {
        val started = forwarder.start(bindingId, port, protocol, open)
        if (started is ChannelResult.Ok) {
            synchronized(lock) {
                listening.update { it + (entryKey to Listener(started.value, protocol, appKey, bindingId, open)) }
            }
            log("forwarding $FORWARD_BIND_HOST:${started.value}/$protocol to $entryKey through the hub")
        }
        return started
    }

    private suspend fun end(entryKey: String, why: String) {
        val held = synchronized(lock) {
            val found = listening.value[entryKey]
            if (found != null) listening.update { it - entryKey }
            found
        } ?: return
        forwarder.stop(held.port, held.protocol)
        log("stopped forwarding $FORWARD_BIND_HOST:${held.port}/${held.protocol} to $entryKey: $why")
        if (entryKey.substringAfter('/') == FORWARD_PANEL_ENTRY) {
            settle(entryKey) { it.copy(localPort = 0) }
        }
    }

    private fun ended(end: TransportForwardEnd) {
        val port = end.listen.substringAfterLast(':').toIntOrNull() ?: return
        val found = synchronized(lock) {
            val match = listening.value.entries.firstOrNull {
                it.value.port == port && it.value.protocol == end.protocol
            }
            if (match != null) listening.update { it - match.key }
            match
        } ?: return
        val held = found.value
        log("the transport ended the forward $FORWARD_BIND_HOST:$port/${held.protocol}: ${end.refusal?.code.orEmpty()}")
        end.refusal?.let { refusal -> settle(held.appKey) { it.copy(error = refusal) } }
        if (held.protocol != FORWARD_PROTOCOL_UDP) return
        scope.launch {
            delay(FORWARD_UDP_RESTART_MILLIS)
            if (current.value[held.appKey]?.isInUse != true || found.key in listening.value) return@launch
            val again = listen(held.bindingId, found.key, held.appKey, held.port, held.protocol, held.open)
            if (again is ChannelResult.Refused) settle(held.appKey) { it.copy(error = again) }
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

    private fun settle(key: String, next: (PortForwardRow) -> PortForwardRow) {
        current.update { rows ->
            val row = next(rows[key] ?: PortForwardRow())
            if (row == PortForwardRow()) rows - key else rows + (key to row)
        }
    }

    private fun entriesOf(hub: HubView, app: ChannelApp): List<ChannelServiceEntry> =
        hub.services.filter { it.appId == app.id && (it.type == "web" || it.type == "port") }

    private fun entryOpen(entryId: String): JsonObject = buildJsonObject {
        put("kind", "connect")
        put("id", entryId)
    }

    /** One listener the transport holds for an entry. */
    private data class Listener(
        val port: Int,
        val protocol: String,
        val appKey: String,
        val bindingId: String,
        val open: JsonObject,
    )

    companion object {
        /**
         * The host a hub's panel is opened under, so each hub's panel keeps its own cookie.
         *
         * @param hubId The hub's id.
         * @return `panel-<slug of the id>.localhost`.
         */
        fun panelHostOf(hubId: String): String =
            "$FORWARD_PANEL_SLUG_PREFIX${hubId.replace(Regex("[^A-Za-z0-9-]"), "-")}.$WEB_LOOPBACK_DOMAIN"

        /**
         * The key of one app or entry.
         *
         * @param bindingId The hub.
         * @param id The app's or the entry's id.
         * @return `<binding>/<id>`.
         */
        fun keyOf(bindingId: String, id: String): String = "$bindingId/$id"

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

        /**
         * The scheme and the path of a `web` entry's url, the parts its local address keeps.
         *
         * @param url The entry's url.
         * @return `http` or `https` with the path, `/` for none; null for any other scheme or an unreadable url.
         */
        fun targetOf(url: String): Pair<String, String>? = try {
            val address = URI(url)
            val scheme = address.scheme?.lowercase().orEmpty()
            if (scheme != "http" && scheme != "https") {
                null
            } else {
                val query = address.rawQuery?.let { "?$it" }.orEmpty()
                scheme to address.rawPath.orEmpty().ifEmpty { "/" } + query
            }
        } catch (_: URISyntaxException) {
            null
        }
    }
}
