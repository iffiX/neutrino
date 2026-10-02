package io.github.iffix.neutrino.channel

import io.github.iffix.neutrino.CHANNEL_STREAM_ID_BYTES
import io.github.iffix.neutrino.CLIENT_BACKOFF_MAX_S
import io.github.iffix.neutrino.CLIENT_BACKOFF_MIN_S
import io.github.iffix.neutrino.CLIENT_CONNECT_TIMEOUT_S
import io.github.iffix.neutrino.CLIENT_HTTPS_DEFAULT_PORT
import io.github.iffix.neutrino.CLIENT_HUB_ROLE
import io.github.iffix.neutrino.CLIENT_IDLE_POLL_INTERVAL_S
import io.github.iffix.neutrino.CLIENT_REFRESH_TIMEOUT_S
import io.github.iffix.neutrino.CLIENT_REFUSAL_CODE_BINDING_UNKNOWN
import io.github.iffix.neutrino.CLIENT_REPORT_INTERVAL_S
import io.github.iffix.neutrino.CLIENT_ROTATE_DELAY_S
import io.github.iffix.neutrino.CLIENT_STREAM_KIND_SERVICE
import io.github.iffix.neutrino.CLIENT_STREAM_TIMEOUT_S
import io.github.iffix.neutrino.CLIENT_WS_CLOSE_NORMAL
import io.github.iffix.neutrino.CLIENT_WS_CLOSE_REFUSED
import io.github.iffix.neutrino.CLIENT_WS_CLOSE_REPLACED
import io.github.iffix.neutrino.binding.BindingStore
import io.github.iffix.neutrino.binding.HubBinding
import java.io.IOException
import java.net.URI
import java.net.URISyntaxException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject

/**
 * The one socket to one hub: a connection round over the hub's addresses, the handshake, the
 * state taken and the reports sent, and the rounds again with the desktop client's backoff.
 *
 * A round tries the address the virtual network prefers, the address the hub's name resolves
 * to, the one that last answered, then the rest. A broken wire waits 5 s, doubled up to 60 s; a
 * refusal the binding survives waits 60 s; `binding_unknown` ends the binding; a socket another
 * replaced waits for [reconnect].
 *
 * @param bindingId The binding the session is for.
 * @param store Where the binding is kept and noted.
 * @param transport How the hub is reached.
 * @param machine What this phone says about itself.
 * @param resolveHubName The IPv4 address `hub.neutrino.internal` resolves to here, or null.
 * @param onUnbound Called with the binding's id and the refusal when the hub no longer knows it.
 * @param clock The time in milliseconds, stamped on the view when the open socket closes.
 * @throws IllegalArgumentException When the store holds no binding with [bindingId].
 */
class HubSession(
    val bindingId: String,
    private val store: BindingStore,
    private val transport: HubTransport,
    private val machine: ClientMachine,
    private val resolveHubName: suspend () -> String?,
    private val onUnbound: (String, ChannelResult.Refused) -> Unit,
    private val clock: () -> Long = System::currentTimeMillis,
) {
    private val current = MutableStateFlow(HubView(binding = requireNotNull(store.get(bindingId))))
    private val news = Channel<Unit>(Channel.CONFLATED)
    private var job: Job? = null
    private var scope: CoroutineScope? = null
    private var refreshTimer: Job? = null
    private var backoffS = CLIENT_BACKOFF_MIN_S
    private var stateHash = ""
    private var isReplaced = false
    private var isUnbound = false

    @Volatile
    private var preferredUrl = ""

    @Volatile
    private var isPreferredOnly = false

    @Volatile
    private var dialling: Channel<ChannelSocketEvent>? = null

    @Volatile
    private var isRoundCut = false

    @Volatile
    private var live: LiveSocket? = null

    /** The hub as the screens read it. */
    val view: StateFlow<HubView> = current.asStateFlow()

    /**
     * Run the rounds until [stop].
     *
     * @param scope Where the loop and the refresh's timer run.
     */
    fun start(scope: CoroutineScope) {
        this.scope = scope
        if (job != null) return
        job = scope.launch {
            while (isActive) {
                val waitS = runOnce()
                withTimeoutOrNull(waitS * 1000) { news.receive() }
            }
        }
    }

    /** End the loop and close the socket. */
    fun stop() {
        job?.cancel()
        job = null
        refreshTimer?.cancel()
        live?.socket?.close(CLIENT_WS_CLOSE_NORMAL, "")
    }

    /** Take the binding back from a socket that replaced this one, and connect now. */
    fun reconnect() {
        if (!isReplaced) return
        isReplaced = false
        backoffS = CLIENT_BACKOFF_MIN_S
        current.update { it.copy(connection = HubConnection.CONNECTING, lastError = null) }
        news.trySend(Unit)
    }

    /** The phone's network changed: a round runs now with the backoff at its floor. */
    fun networkChanged() {
        backoffS = CLIENT_BACKOFF_MIN_S
        live?.socket?.close(CLIENT_WS_CLOSE_NORMAL, "network changed")
        news.trySend(Unit)
    }

    /** The app came back to the foreground: a hub with no open socket runs a round now with the backoff at its floor. */
    fun resume() {
        if (live != null || isReplaced || isUnbound) return
        backoffS = CLIENT_BACKOFF_MIN_S
        news.trySend(Unit)
    }

    /**
     * Try one address first in every round, or only that address: the hub's address on a virtual
     * network this phone is on. A socket open on another address is closed so a round runs
     * through the preferred one now.
     *
     * @param url The address, or empty to prefer none; a hub kept to one address with no open
     *   socket then runs a round now.
     * @param isOnly Whether a round tries that address and no other; a round busy on other
     *   addresses then ends at once, and the next runs now.
     */
    fun preferAddress(url: String, isOnly: Boolean = false) {
        val wasOnly = isPreferredOnly
        isPreferredOnly = isOnly && url.isNotEmpty()
        if (url == preferredUrl) return
        preferredUrl = url
        if (url.isEmpty()) {
            if (wasOnly && live == null) {
                backoffS = CLIENT_BACKOFF_MIN_S
                news.trySend(Unit)
            }
            return
        }
        backoffS = CLIENT_BACKOFF_MIN_S
        val socket = live
        if (socket != null && current.value.connectedAddress != url) {
            socket.socket.close(CLIENT_WS_CLOSE_NORMAL, "network changed")
        }
        if (isPreferredOnly) {
            isRoundCut = true
            dialling?.trySend(ChannelSocketEvent.Failed(unreachable("the round gave way to $url")))
        }
        news.trySend(Unit)
    }

    /**
     * A person pressed refresh: the error line goes, and the hub is asked again. A connected hub
     * gets a report with `is_refresh`; a connecting or down hub gets a round now. A replaced or
     * disabled hub takes no refresh. The refresh ends on a state frame, a code, or after 10 s.
     *
     * @return Whether the hub entered refreshing, or already was.
     */
    fun refresh(): Boolean {
        val connection = current.value.connection
        if (connection == HubConnection.REPLACED || connection == HubConnection.DISABLED || isUnbound) return false
        if (current.value.jobs.isRefreshing) return true
        current.update { it.copy(lastError = null, jobs = it.jobs.copy(isRefreshing = true)) }
        refreshTimer?.cancel()
        refreshTimer = scope?.launch {
            delay(CLIENT_REFRESH_TIMEOUT_S * 1000)
            refreshTimer = null
            current.update { it.copy(jobs = it.jobs.copy(isRefreshing = false)) }
        }
        val socket = live
        if (socket == null) {
            backoffS = CLIENT_BACKOFF_MIN_S
            news.trySend(Unit)
        } else if (!report(socket.socket, isRefresh = true)) {
            socket.socket.close(CLIENT_WS_CLOSE_NORMAL, "report not taken")
        }
        return true
    }

    /**
     * Open a stream on the live socket.
     *
     * @param kind The kind.
     * @param args Its arguments.
     * @param hasBytes Whether it carries bytes.
     * @return The stream, or `hub_unreachable` while the hub is not connected.
     */
    fun openStream(
        kind: String,
        args: Map<String, JsonElement>,
        hasBytes: Boolean = false,
    ): ChannelResult<ChannelStream> {
        val socket = live ?: return ChannelResult.refused("hub_unreachable", "detail" to "this hub is not connected")
        return socket.streams.open(kind, args, hasBytes)
    }

    /**
     * The material one published entry takes from the hub: the close of a `service` stream.
     *
     * @param entryId The entry's id.
     * @return The close's params, or its refusal.
     */
    suspend fun openService(entryId: String): ChannelResult<JsonObject> =
        when (val opened = openStream(CLIENT_STREAM_KIND_SERVICE, ChannelFrames.args("id" to entryId))) {
            is ChannelResult.Refused -> opened
            is ChannelResult.Ok -> opened.value.awaitClose(CLIENT_STREAM_TIMEOUT_S * 1000)
        }

    /**
     * One round, or one idle turn.
     *
     * @return How many seconds to wait before the next.
     */
    internal suspend fun runOnce(): Long {
        if (isReplaced || isUnbound) return CLIENT_IDLE_POLL_INTERVAL_S
        val binding = store.get(bindingId) ?: return CLIENT_IDLE_POLL_INTERVAL_S
        current.update { it.copy(connection = HubConnection.CONNECTING) }
        isRoundCut = false
        val only = preferredUrl.takeIf { isPreferredOnly }
        val nameUrl = if (only != null) "" else resolveHubName()?.let { nameUrlOf(binding.gatewayUrl, it) }.orEmpty()
        val urls = if (only != null) listOf(only) else binding.candidateUrls(nameUrl, preferredUrl)
        var untrusted: ChannelResult.Refused? = null
        var failure: ChannelResult.Refused? = null
        for ((index, url) in urls.withIndex()) {
            if (index > 0) delay(CLIENT_ROTATE_DELAY_S * 1000)
            if (isRoundCut) return cutRound()
            val events = Channel<ChannelSocketEvent>(Channel.UNLIMITED)
            dialling = events
            val socket = transport.connect(url, binding.fingerprint, events)
            val outcome = handshake(binding, socket, events)
            dialling = null
            if (isRoundCut && outcome !is Handshake.Welcomed) {
                socket.close(CLIENT_WS_CLOSE_NORMAL, "")
                return cutRound()
            }
            when (outcome) {
                is Handshake.Welcomed -> return afterServing(serve(url, socket, events, outcome.welcome))

                is Handshake.Rejected -> {
                    socket.close(CLIENT_WS_CLOSE_NORMAL, "")
                    return onRejected(outcome.refusal)
                }

                is Handshake.Failed -> {
                    socket.close(CLIENT_WS_CLOSE_NORMAL, "")
                    if (outcome.refusal.code != "hub_untrusted") {
                        failure = outcome.refusal
                    } else if (url != nameUrl || url in binding.storedUrls) {
                        untrusted = outcome.refusal
                    }
                }
            }
        }
        untrusted?.let { return onRejected(it) }
        return onUnreachable(failure ?: ChannelResult.refused("hub_unreachable", "detail" to "no address"))
    }

    private fun cutRound(): Long {
        news.tryReceive()
        return 0
    }

    private suspend fun handshake(
        binding: HubBinding,
        socket: ChannelSocket,
        events: Channel<ChannelSocketEvent>,
    ): Handshake = withTimeoutOrNull(CLIENT_CONNECT_TIMEOUT_S * 1000) {
        when (val first = events.receive()) {
            is ChannelSocketEvent.Opened -> Unit
            is ChannelSocketEvent.Failed -> return@withTimeoutOrNull Handshake.Failed(first.refusal)
            else -> return@withTimeoutOrNull Handshake.Failed(unreachable("the socket did not open"))
        }
        socket.sendText(ChannelFrames.hello(binding, machine).toString())
        val answer = when (val event = events.receive()) {
            is ChannelSocketEvent.Text -> try {
                ChannelInbound.decode(event.text)
            } catch (_: IllegalArgumentException) {
                null
            }

            is ChannelSocketEvent.Closed -> return@withTimeoutOrNull closedAtHandshake(event)

            is ChannelSocketEvent.Failed -> return@withTimeoutOrNull Handshake.Failed(event.refusal)

            else -> null
        }
        when {
            answer is ChannelInbound.Refused -> Handshake.Rejected(answer.refusal)

            answer is ChannelInbound.Welcome && answer.role == CLIENT_HUB_ROLE -> {
                report(socket, isRefresh = current.value.jobs.isRefreshing)
                Handshake.Welcomed(answer)
            }

            else -> Handshake.Failed(unreachable("the hub's first frame is not a welcome"))
        }
    } ?: Handshake.Failed(unreachable("the hub did not answer in ${CLIENT_CONNECT_TIMEOUT_S}s"))

    private fun closedAtHandshake(event: ChannelSocketEvent.Closed): Handshake = when (event.code) {
        CLIENT_WS_CLOSE_REFUSED -> Handshake.Rejected(ChannelResult.refused("hub_refused"))
        else -> Handshake.Failed(unreachable("the hub closed the socket (${event.code})"))
    }

    private suspend fun serve(
        url: String,
        socket: ChannelSocket,
        events: Channel<ChannelSocketEvent>,
        welcome: ChannelInbound.Welcome,
    ): ChannelResult.Refused? {
        val streams = ChannelStreamRegistry(socket)
        live = LiveSocket(socket, streams)
        backoffS = CLIENT_BACKOFF_MIN_S
        note { it.copy(gatewayUrl = url, hubId = welcome.id, hubName = welcome.name) }
        current.update {
            it.copy(
                connection = HubConnection.CONNECTED,
                software = welcome.software,
                lastError = null,
                connectedAddress = url,
                hasConnected = true,
                droppedAtMillis = 0,
            )
        }
        var failure: ChannelResult.Refused? = null
        coroutineScope {
            val reporter = launch {
                while (isActive) {
                    delay(CLIENT_REPORT_INTERVAL_S * 1000)
                    report(socket)
                }
            }
            try {
                failure = readUntilEnd(socket, events, streams)
            } finally {
                reporter.cancel()
            }
        }
        return failure
    }

    private suspend fun readUntilEnd(
        socket: ChannelSocket,
        events: Channel<ChannelSocketEvent>,
        streams: ChannelStreamRegistry,
    ): ChannelResult.Refused? {
        var failure: ChannelResult.Refused? = null
        try {
            while (true) {
                when (val event = events.receive()) {
                    is ChannelSocketEvent.Text -> failure = dispatch(event.text, socket, streams)

                    is ChannelSocketEvent.Binary -> if (event.bytes.size >= CHANNEL_STREAM_ID_BYTES) {
                        streams.takeBinary(event.bytes)
                    }

                    is ChannelSocketEvent.Closed -> {
                        failure = when (event.code) {
                            CLIENT_WS_CLOSE_REPLACED -> {
                                isReplaced = true
                                null
                            }

                            CLIENT_WS_CLOSE_REFUSED -> ChannelResult.refused("hub_refused")

                            else -> null
                        }
                        break
                    }

                    is ChannelSocketEvent.Failed -> break

                    is ChannelSocketEvent.Opened -> Unit
                }
                if (failure != null) break
            }
        } finally {
            live = null
            streams.endAll()
            socket.close(CLIENT_WS_CLOSE_NORMAL, "")
            current.update {
                it.copy(connection = HubConnection.CONNECTING, connectedAddress = "", droppedAtMillis = clock())
            }
        }
        return failure
    }

    private fun dispatch(text: String, socket: ChannelSocket, streams: ChannelStreamRegistry): ChannelResult.Refused? {
        val frame = try {
            ChannelInbound.decode(text)
        } catch (error: IllegalArgumentException) {
            current.update {
                it.copy(lastError = ChannelResult.refused("hub_reply_unreadable", "detail" to (error.message ?: "")))
            }
            return null
        }
        when (frame) {
            is ChannelInbound.State -> {
                takeState(frame.state)
                report(socket)
            }

            is ChannelInbound.Close -> streams.takeClose(frame)

            is ChannelInbound.Credit -> streams.takeCredit(frame)

            is ChannelInbound.Open -> streams.refuse(frame)

            is ChannelInbound.Refused -> return frame.refusal

            is ChannelInbound.Welcome, is ChannelInbound.Unknown -> Unit
        }
        return null
    }

    private fun takeState(state: ChannelClientState) {
        stateHash = state.hash
        note { binding ->
            binding.copy(
                gatewayUrls = state.urls.ifEmpty { binding.gatewayUrls },
                overlays = state.overlays,
            )
        }
        endRefresh()
        current.update {
            it.copy(
                connection = if (state.isDisabled) HubConnection.DISABLED else HubConnection.CONNECTED,
                services = state.services,
                terminals = state.terminals,
                lastError = null,
            )
        }
    }

    private fun report(socket: ChannelSocket, isRefresh: Boolean = false): Boolean =
        socket.sendText(ChannelFrames.report(stateHash, machine, isRefresh).toString())

    private fun note(change: (HubBinding) -> HubBinding) {
        val kept = try {
            store.update(bindingId, change)
        } catch (_: IOException) {
            null
        } ?: return
        current.update { it.copy(binding = kept) }
    }

    private fun endRefresh() {
        refreshTimer?.cancel()
        refreshTimer = null
        current.update { it.copy(jobs = it.jobs.copy(isRefreshing = false)) }
    }

    private fun afterServing(failure: ChannelResult.Refused?): Long {
        if (failure != null) return onRejected(failure)
        if (isReplaced) {
            endRefresh()
            current.update { it.copy(connection = HubConnection.REPLACED, lastError = null) }
            return CLIENT_IDLE_POLL_INTERVAL_S
        }
        current.update { it.copy(connection = HubConnection.CONNECTING, lastError = null) }
        return CLIENT_BACKOFF_MIN_S
    }

    private fun onUnreachable(refusal: ChannelResult.Refused): Long {
        val waitS = backoffS
        backoffS = minOf(backoffS * 2, CLIENT_BACKOFF_MAX_S)
        endRefresh()
        current.update { it.copy(connection = HubConnection.DOWN, lastError = refusal) }
        return waitS
    }

    private fun onRejected(refusal: ChannelResult.Refused): Long {
        endRefresh()
        current.update { it.copy(connection = HubConnection.DOWN, lastError = refusal) }
        if (refusal.code == CLIENT_REFUSAL_CODE_BINDING_UNKNOWN) {
            isUnbound = true
            onUnbound(bindingId, refusal)
            return CLIENT_IDLE_POLL_INTERVAL_S
        }
        return CLIENT_BACKOFF_MAX_S
    }

    private fun unreachable(detail: String) = ChannelResult.refused("hub_unreachable", "detail" to detail)

    private fun nameUrlOf(gatewayUrl: String, address: String): String = try {
        val parts = URI(gatewayUrl)
        val port = if (parts.port > 0) parts.port else CLIENT_HTTPS_DEFAULT_PORT
        "${parts.scheme}://$address:$port"
    } catch (_: URISyntaxException) {
        ""
    }

    private class LiveSocket(val socket: ChannelSocket, val streams: ChannelStreamRegistry)

    private sealed interface Handshake {
        data class Welcomed(val welcome: ChannelInbound.Welcome) : Handshake

        data class Rejected(val refusal: ChannelResult.Refused) : Handshake

        data class Failed(val refusal: ChannelResult.Refused) : Handshake
    }
}
