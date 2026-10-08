package io.github.iffix.neutrino.channel

import android.os.SystemClock
import android.util.Log
import io.github.iffix.neutrino.CHANNEL_STREAM_ID_BYTES
import io.github.iffix.neutrino.CLIENT_BACKOFF_MAX_S
import io.github.iffix.neutrino.CLIENT_BACKOFF_MIN_S
import io.github.iffix.neutrino.CLIENT_CONNECT_TIMEOUT_S
import io.github.iffix.neutrino.CLIENT_HTTPS_DEFAULT_PORT
import io.github.iffix.neutrino.CLIENT_HUB_ROLE
import io.github.iffix.neutrino.CLIENT_IDLE_POLL_INTERVAL_S
import io.github.iffix.neutrino.CLIENT_JOIN_PATH
import io.github.iffix.neutrino.CLIENT_LOG_TAG
import io.github.iffix.neutrino.CLIENT_PING_INTERVAL_S
import io.github.iffix.neutrino.CLIENT_PROTOCOL_REFUSAL_CODES
import io.github.iffix.neutrino.CLIENT_REFRESH_TIMEOUT_S
import io.github.iffix.neutrino.CLIENT_REFUSAL_CODE_ADMISSION_PAUSED
import io.github.iffix.neutrino.CLIENT_REFUSAL_CODE_BINDING_UNKNOWN
import io.github.iffix.neutrino.CLIENT_REPORT_INTERVAL_S
import io.github.iffix.neutrino.CLIENT_STREAM_KIND_CONNECT
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
import java.util.UUID
import kotlin.math.roundToLong
import kotlin.time.Duration.Companion.nanoseconds
import kotlin.time.DurationUnit
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.selects.select
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.longOrNull

/**
 * The one socket to one hub: a connection round over the hub's addresses, the handshake, the
 * state taken and the reports sent, and the rounds again with the desktop client's backoff.
 *
 * A round dials at once the hub's address on the virtual network that is up, the address the
 * hub's name resolves to, and the binding's addresses, each with its own connect time. The first
 * socket to open on the pinned certificate is the round's: the others are closed before any
 * hello, and the one hello of the round goes there. The view is `connecting` while a round dials,
 * `connected` while the socket is open, and `waiting` with a [HubWaitReason] otherwise, with the
 * moment of the next round when one is due. Every address failing waits 5 s, doubled up to 60 s,
 * as `hub_silent`, or `hub_off_overlay` while this phone is on the hub's virtual network, or as
 * `no_network` with no next round while the phone has no network; `hub_untrusted` waits 60 s;
 * `binding_unknown`, a protocol refusal and a socket another replaced wait for a person. A socket
 * that closes runs the next round at once. A round that fails on an exception waits like every
 * address failing. The open socket sends a `ping` frame every 20 s and once after a move, and the
 * `pong` echoing its nonce sets the view's `rttMs`.
 *
 * A network change ([networkChanged]) runs a round at once. On a hub with no open socket it ends
 * the wait and the round still dialling, whose sockets are closed. On a connected hub that round
 * runs beside the channel: its winner takes the channel only when its path ranks higher than the
 * channel's, or ranks the same and opened faster; a winner that is no better is closed before
 * its hello. A better winner says hello, and the hub's `replaced` close of the socket moved off
 * is expected and not shown.
 *
 * A binding whose ticket is unspent spends it at the round's socket's address, and the hello
 * follows on that socket with the token it returned. A refusal of the ticket is `join_refused`
 * with its code, and no round runs after it, except `admission_paused`: the ticket is kept, and
 * the join runs again after the `retry_after_s` it names.
 *
 * @param bindingId The binding the session is for.
 * @param store Where the binding is kept and noted.
 * @param transport How the hub is reached.
 * @param machine What this phone says about itself.
 * @param resolveHubName The IPv4 address `hub.neutrino.internal` resolves to here, or null.
 * @param onJoined Called with the binding's id and the hub's id for it once its ticket is spent.
 * @param clock The time in milliseconds, stamped on the view when the open socket closes and for the next round.
 * @param localNetworks The networks this phone holds an address in, read at each comparison of paths.
 * @param nanoClock The time in nanoseconds, by which each socket's opening and each ping's round trip are measured.
 * @param hasNetwork Whether the phone has a network at all, read when every address of a round failed.
 * @throws IllegalArgumentException When the store holds no binding with [bindingId].
 */
class HubSession(
    val bindingId: String,
    private val store: BindingStore,
    private val transport: HubTransport,
    private val machine: ClientMachine,
    private val resolveHubName: suspend () -> String?,
    private val onJoined: (String, String) -> Unit = { _, _ -> },
    private val clock: () -> Long = System::currentTimeMillis,
    private val localNetworks: () -> List<ChannelLocalNetwork> = ChannelPath::deviceNetworks,
    private val nanoClock: () -> Long = SystemClock::elapsedRealtimeNanos,
    private val hasNetwork: () -> Boolean = { true },
) {
    private val current = MutableStateFlow(HubView(requireNotNull(store.get(bindingId))))
    private val news = Channel<Unit>(Channel.CONFLATED)
    private var job: Job? = null
    private var scope: CoroutineScope? = null
    private var refreshTimer: Job? = null
    private var backoffS = CLIENT_BACKOFF_MIN_S
    private var stateHash = ""

    @Volatile
    private var held: HubWaitReason? = null

    private val changes = Channel<Unit>(Channel.CONFLATED)
    private val moves = Channel<Moved>(Channel.UNLIMITED)

    @Volatile
    private var overlay: ChannelOverlayRoute? = null

    @Volatile
    private var relayUrl = ""

    @Volatile
    private var movingFrom: ChannelSocket? = null

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
                val waitS = try {
                    runOnce()
                } catch (error: Exception) {
                    if (error is CancellationException) throw error
                    Log.e(CLIENT_LOG_TAG, "hub ${current.value.binding.title}: the round failed", error)
                    val detail = error.message ?: error.javaClass.simpleName
                    onUnreachable(ChannelResult.refused("client_internal", "error" to detail))
                }
                if (waitS > 0) withTimeoutOrNull(waitS * 1000) { news.receive() }
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
        if (held != HubWaitReason.REPLACED) return
        held = null
        backoffS = CLIENT_BACKOFF_MIN_S
        current.update { it.dialling() }
        news.trySend(Unit)
    }

    /**
     * A network changed: a virtual network of the hub's turned on or its peer list changed, the
     * phone's connectivity changed, or the hub's state named other addresses. A hub that waits for
     * a person, or the hub's admission, runs nothing; a hub with no open socket ends its wait and
     * the round still dialling, and runs a round now with the backoff at its floor; a connected hub
     * runs a round beside its channel.
     */
    fun networkChanged() {
        when (held) {
            null -> Unit
            HubWaitReason.NO_NETWORK -> held = null
            else -> return
        }
        val reason = current.value.waitReason
        if (reason == HubWaitReason.DISABLED) return
        if (live != null) {
            changes.trySend(Unit)
            return
        }
        if (reason == HubWaitReason.ADMISSION_PAUSED) return
        backoffS = CLIENT_BACKOFF_MIN_S
        news.trySend(Unit)
    }

    /** The app came back to the foreground: a hub with no open socket runs a round now, as on a network change. */
    fun resume() {
        if (live == null) networkChanged()
    }

    /**
     * The hub's virtual network this phone is on, or none: its address is a candidate of every
     * round, and a network turning on is a network change.
     *
     * @param route The network that is on, or null once it is off.
     */
    fun overlayChanged(route: ChannelOverlayRoute?) {
        val previous = overlay
        overlay = route
        if (route != null && route != previous) networkChanged()
    }

    /**
     * A person pressed refresh: the hub is asked again. A connected hub gets a report with
     * `is_refresh`; a hub with no open socket ends its wait and the round still dialling, and runs
     * a round now. A replaced or disabled hub, or one that waits only for Leave, takes no refresh.
     * The refresh ends on a state frame, a code, or after 10 s.
     *
     * @return Whether the hub entered refreshing, or already was.
     */
    fun refresh(): Boolean {
        val isStopped = held == HubWaitReason.REPLACED || held == HubWaitReason.UNKNOWN_DEVICE ||
            held == HubWaitReason.JOIN_REFUSED
        if (isStopped || current.value.isDisabled) return false
        if (current.value.jobs.isRefreshing) return true
        current.update { it.copy(jobs = it.jobs.copy(isRefreshing = true)) }
        refreshTimer?.cancel()
        refreshTimer = scope?.launch {
            delay(CLIENT_REFRESH_TIMEOUT_S * 1000)
            refreshTimer = null
            current.update { it.copy(jobs = it.jobs.copy(isRefreshing = false)) }
        }
        val socket = live
        if (socket == null) {
            held = null
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
        openService(ChannelFrames.args("id" to entryId))

    /**
     * What the hub hands this phone on a `service` stream: an entry's material for `{id}`, the
     * panel's one-time `{token}` for `{is_panel: true}`.
     *
     * @param args The stream's arguments.
     * @return The close's params, or its refusal.
     */
    suspend fun openService(args: Map<String, JsonElement>): ChannelResult<JsonObject> =
        when (val opened = openStream(CLIENT_STREAM_KIND_SERVICE, args)) {
            is ChannelResult.Refused -> opened
            is ChannelResult.Ok -> opened.value.awaitClose(CLIENT_STREAM_TIMEOUT_S * 1000)
        }

    /**
     * Open one `connect` stream: one TCP connection to a published entry or to the hub's panel.
     *
     * @param args `{id}` for an entry, `{is_panel: true}` for the panel.
     * @return The stream, or `hub_unreachable` while the hub is not connected.
     */
    fun openConnect(args: Map<String, JsonElement>): ChannelResult<ChannelStream> =
        openStream(CLIENT_STREAM_KIND_CONNECT, args, hasBytes = true)

    /**
     * One round, or one idle turn.
     *
     * @return How many seconds to wait before the next; 0 runs the next at once.
     */
    internal suspend fun runOnce(): Long {
        if (held != null) return CLIENT_IDLE_POLL_INTERVAL_S
        var binding = store.get(bindingId) ?: return CLIENT_IDLE_POLL_INTERVAL_S
        news.tryReceive()
        current.update { it.dialling() }
        val nameUrl = nameUrlOf(binding)
        val urls = binding.candidateUrls(nameUrl, overlay?.url.orEmpty())
        val round = dialAll(urls, binding.fingerprint, isInterruptible = true)
        if (round.isInterrupted) {
            log("the round ended before its dials did: a network change or a refresh starts the next")
            return 0
        }
        var untrusted: ChannelResult.Refused? = null
        var failure: ChannelResult.Refused? = null
        for ((url, refusal) in round.refusals) {
            if (refusal.code != "hub_untrusted") {
                failure = refusal
            } else if (url != nameUrl || url in binding.storedUrls) {
                untrusted = refusal
            }
        }
        val winner = round.winner
        if (winner == null) {
            untrusted?.let { return onRejected(it) }
            return onUnreachable(failure ?: unreachable("no address"))
        }
        if (binding.isPending) {
            when (val spent = spend(binding, winner.url)) {
                is ChannelResult.Ok -> binding = spent.value

                is ChannelResult.Refused -> {
                    winner.socket.close(CLIENT_WS_CLOSE_NORMAL, "")
                    return when (spent.code) {
                        "hub_unreachable" -> onUnreachable(spent)
                        "hub_untrusted" -> onRejected(spent)
                        CLIENT_REFUSAL_CODE_ADMISSION_PAUSED -> onAdmissionPaused(spent)
                        else -> onJoinRefused(spent)
                    }
                }
            }
        }
        return when (val outcome = handshake(binding, winner.socket, winner.events)) {
            is Handshake.Welcomed -> afterServing(serve(winner, outcome.welcome))

            is Handshake.Rejected -> {
                winner.socket.close(CLIENT_WS_CLOSE_NORMAL, "")
                onRejected(outcome.refusal)
            }

            is Handshake.Failed -> {
                winner.socket.close(CLIENT_WS_CLOSE_NORMAL, "")
                onUnreachable(outcome.refusal)
            }
        }
    }

    /**
     * Dial every address at once, each with its own connect time. The first socket that opens on
     * the pinned certificate is the round's; every other socket, and every socket of a round that
     * is cancelled or interrupted, is closed before this returns.
     *
     * @param urls The round's addresses.
     * @param fingerprint The pinned SHA-256.
     * @param isInterruptible Whether a network change or a refresh ends the round before its dials do.
     * @return The round's socket or null, the refusal of each address that failed, and whether it was interrupted.
     */
    private suspend fun dialAll(urls: List<String>, fingerprint: String, isInterruptible: Boolean): Round {
        val opens = Channel<Dialled>(Channel.UNLIMITED)
        val sockets = mutableListOf<DialledSocket>()
        val refusals = mutableListOf<Pair<String, ChannelResult.Refused>>()
        var winner: DialledSocket? = null
        var isInterrupted = false
        var isSettled = false
        try {
            for (url in urls) {
                val events = Channel<ChannelSocketEvent>(Channel.UNLIMITED)
                val startedNanos = nanoClock()
                sockets += DialledSocket(url, transport.connect(url, fingerprint, events), events, startedNanos)
            }
            coroutineScope {
                val watchers = sockets.map { dialled ->
                    launch {
                        val first = withTimeoutOrNull(CLIENT_CONNECT_TIMEOUT_S * 1000) { dialled.events.receive() }
                            ?: ChannelSocketEvent.Failed(
                                unreachable("the address did not open in ${CLIENT_CONNECT_TIMEOUT_S}s"),
                            )
                        dialled.openNanos = nanoClock() - dialled.startedNanos
                        opens.send(Dialled(dialled, first))
                    }
                }
                var waiting = sockets.size
                while (winner == null && waiting > 0) {
                    val dial = if (isInterruptible) nextDialOrNews(opens) else opens.receive()
                    if (dial == null) {
                        isInterrupted = true
                        break
                    }
                    val dialled = dial.socket
                    waiting -= 1
                    when (val event = dial.event) {
                        is ChannelSocketEvent.Opened -> winner = dialled
                        is ChannelSocketEvent.Failed -> refusals += dialled.url to event.refusal
                        else -> refusals += dialled.url to unreachable("the socket did not open")
                    }
                }
                watchers.forEach { it.cancel() }
            }
            isSettled = true
        } finally {
            val kept = if (isSettled) winner else null
            sockets.filter { it !== kept }.forEach { it.socket.close(CLIENT_WS_CLOSE_NORMAL, "") }
        }
        return Round(winner, refusals, isInterrupted)
    }

    private suspend fun nextDialOrNews(opens: Channel<Dialled>): Dialled? = select {
        opens.onReceive { it }
        news.onReceive { null }
    }

    /**
     * A round beside the open channel: its winner takes the channel only on a better path, and
     * is closed before its hello otherwise.
     */
    private suspend fun moveIfBetter() {
        val from = live ?: return
        val binding = store.get(bindingId) ?: return
        val urls = binding.candidateUrls(nameUrlOf(binding), overlay?.url.orEmpty())
        val winner = dialAll(urls, binding.fingerprint, isInterruptible = false).winner ?: return
        val path = pathOf(winner.url)
        val livePath = pathOf(from.url)
        val isBetter = path.rank < livePath.rank || (path.rank == livePath.rank && winner.openNanos < from.openNanos)
        if (!isBetter || live !== from) {
            winner.socket.close(CLIENT_WS_CLOSE_NORMAL, "")
            log(
                "the channel stays on ${from.url} (${livePath.wireName}); ${winner.url} (${path.wireName}) is no better",
            )
            return
        }
        movingFrom = from.socket
        var isTaken = false
        try {
            val outcome = handshake(binding, winner.socket, winner.events)
            if (outcome is Handshake.Welcomed) {
                moves.send(Moved(winner, outcome.welcome))
                isTaken = true
            } else {
                log("the channel stays on ${from.url}: ${winner.url} answered no welcome")
            }
        } finally {
            if (!isTaken) {
                movingFrom = null
                winner.socket.close(CLIENT_WS_CLOSE_NORMAL, "")
            }
        }
    }

    private fun pathOf(url: String): ChannelPath = ChannelPath.of(url, overlay, relayUrl, localNetworks())

    private suspend fun nameUrlOf(binding: HubBinding): String {
        val firstUrl = binding.storedUrls.firstOrNull() ?: return ""
        return resolveHubName()?.let { nameUrlOf(firstUrl, it) }.orEmpty()
    }

    private fun log(text: String) {
        Log.i(CLIENT_LOG_TAG, "hub ${current.value.binding.title}: $text")
    }

    private suspend fun spend(binding: HubBinding, url: String): ChannelResult<HubBinding> {
        val body = ChannelFrames.joinRequest(binding.ticket, machine)
        val answer = when (val posted = transport.post(url, CLIENT_JOIN_PATH, binding.fingerprint, body)) {
            is ChannelResult.Refused -> return posted
            is ChannelResult.Ok -> posted.value
        }
        val id = (answer["id"] as? JsonPrimitive)?.content.orEmpty()
        val token = (answer["token"] as? JsonPrimitive)?.content.orEmpty()
        if (id.isEmpty() || token.isEmpty()) return ChannelResult.refused("enroll_no_token")
        val kept = try {
            store.update(bindingId) { it.copy(hubBindingId = id, token = token, ticket = "", gatewayUrl = url) }
        } catch (error: IOException) {
            return ChannelResult.refused("client_internal", "error" to (error.message ?: "IOException"))
        } ?: return ChannelResult.refused("client_internal", "error" to "the binding is gone")
        current.update { it.copy(binding = kept) }
        onJoined(bindingId, id)
        return ChannelResult.Ok(kept)
    }

    private fun onJoinRefused(refusal: ChannelResult.Refused): Long = hold(HubWaitReason.JOIN_REFUSED, refusal)

    private fun onAdmissionPaused(refusal: ChannelResult.Refused): Long {
        val retryS = (refusal.params["retry_after_s"] as? JsonPrimitive)?.longOrNull ?: CLIENT_BACKOFF_MAX_S
        return waitFor(HubWaitReason.ADMISSION_PAUSED, refusal, retryS.coerceAtLeast(1))
    }

    private suspend fun handshake(
        binding: HubBinding,
        socket: ChannelSocket,
        events: Channel<ChannelSocketEvent>,
    ): Handshake = withTimeoutOrNull(CLIENT_CONNECT_TIMEOUT_S * 1000) {
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

    private suspend fun serve(winner: DialledSocket, welcome: ChannelInbound.Welcome): ChannelResult.Refused? {
        changes.tryReceive()
        if (news.tryReceive().isSuccess) changes.trySend(Unit)
        takeChannel(winner, welcome)
        var failure: ChannelResult.Refused? = null
        coroutineScope {
            val reporter = launch {
                while (isActive) {
                    delay(CLIENT_REPORT_INTERVAL_S * 1000)
                    live?.let { report(it.socket) }
                }
            }
            val pinger = launch {
                while (isActive) {
                    live?.let { ping(it) }
                    delay(CLIENT_PING_INTERVAL_S * 1000)
                }
            }
            val mover = launch {
                for (change in changes) moveIfBetter()
            }
            try {
                failure = readUntilEnd()
            } finally {
                reporter.cancel()
                pinger.cancel()
                withContext(NonCancellable) { mover.cancelAndJoin() }
                generateSequence { moves.tryReceive().getOrNull() }.forEach {
                    it.socket.socket.close(CLIENT_WS_CLOSE_NORMAL, "")
                }
            }
        }
        return failure
    }

    private fun takeChannel(winner: DialledSocket, welcome: ChannelInbound.Welcome) {
        live =
            LiveSocket(winner.socket, ChannelStreamRegistry(winner.socket), winner.url, winner.events, winner.openNanos)
        backoffS = CLIENT_BACKOFF_MIN_S
        note { it.copy(gatewayUrl = winner.url, hubId = welcome.id, hubName = welcome.name) }
        current.update {
            it.copy(
                connection = HubConnection.CONNECTED,
                waitReason = null,
                waitRefusal = null,
                nextRoundAtMillis = 0,
                software = welcome.software,
                connectedAddress = winner.url,
                hasConnected = true,
                droppedAtMillis = 0,
                rttMs = null,
            )
        }
    }

    private fun moveTo(moved: Moved) {
        val previous = live
        movingFrom = null
        takeChannel(moved.socket, moved.welcome)
        previous?.streams?.endAll()
        previous?.socket?.close(CLIENT_WS_CLOSE_NORMAL, "")
        log("the channel moved from ${previous?.url.orEmpty()} to ${moved.socket.url}")
        live?.let { ping(it) }
    }

    private fun ping(socket: LiveSocket) {
        val nonce = UUID.randomUUID().toString()
        socket.pingSentNanos = nanoClock()
        socket.pingNonce = nonce
        socket.socket.sendText(ChannelFrames.ping(nonce).toString())
    }

    private fun takePong(nonce: String, reading: LiveSocket) {
        if (nonce.isEmpty() || nonce != reading.pingNonce) return
        reading.pingNonce = ""
        val rttMs = (nanoClock() - reading.pingSentNanos).nanoseconds.toDouble(DurationUnit.MILLISECONDS).roundToLong()
        current.update { it.copy(rttMs = rttMs) }
    }

    private suspend fun readUntilEnd(): ChannelResult.Refused? {
        var failure: ChannelResult.Refused? = null
        try {
            while (true) {
                val reading = live ?: break
                val step = select {
                    reading.events.onReceive { Step.Event(it) }
                    moves.onReceive { Step.Move(it) }
                }
                if (step is Step.Move) {
                    moveTo(step.moved)
                    continue
                }
                when (val event = (step as Step.Event).event) {
                    is ChannelSocketEvent.Text -> failure = dispatch(event.text, reading)

                    is ChannelSocketEvent.Binary -> if (event.bytes.size >= CHANNEL_STREAM_ID_BYTES) {
                        reading.streams.takeBinary(event.bytes)
                    }

                    is ChannelSocketEvent.Opened -> Unit

                    is ChannelSocketEvent.Closed, is ChannelSocketEvent.Failed -> {
                        if (movingFrom === reading.socket) {
                            val moved = withTimeoutOrNull(CLIENT_CONNECT_TIMEOUT_S * 1000) { moves.receive() }
                            if (moved != null) {
                                moveTo(moved)
                                continue
                            }
                        }
                        if (event is ChannelSocketEvent.Closed) failure = closedWhileServing(event)
                        break
                    }
                }
                if (failure != null) break
            }
        } finally {
            val ending = live
            live = null
            movingFrom = null
            ending?.streams?.endAll()
            ending?.socket?.close(CLIENT_WS_CLOSE_NORMAL, "")
            current.update {
                it.dialling().copy(
                    connectedAddress = "",
                    droppedAtMillis = clock(),
                    rttMs = null,
                )
            }
        }
        return failure
    }

    private fun closedWhileServing(event: ChannelSocketEvent.Closed): ChannelResult.Refused? = when (event.code) {
        CLIENT_WS_CLOSE_REPLACED -> {
            held = HubWaitReason.REPLACED
            null
        }

        CLIENT_WS_CLOSE_REFUSED -> ChannelResult.refused("hub_refused")

        else -> null
    }

    private fun dispatch(text: String, reading: LiveSocket): ChannelResult.Refused? {
        val frame = try {
            ChannelInbound.decode(text)
        } catch (error: IllegalArgumentException) {
            log("a frame the hub sent does not read: ${error.message.orEmpty()}")
            return null
        }
        when (frame) {
            is ChannelInbound.State -> {
                takeState(frame.state)
                report(reading.socket)
            }

            is ChannelInbound.Close -> reading.streams.takeClose(frame)

            is ChannelInbound.Credit -> reading.streams.takeCredit(frame)

            is ChannelInbound.Open -> reading.streams.refuse(frame)

            is ChannelInbound.Pong -> takePong(frame.nonce, reading)

            is ChannelInbound.Refused -> return frame.refusal

            is ChannelInbound.Welcome, is ChannelInbound.Unknown -> Unit
        }
        return null
    }

    private fun takeState(state: ChannelClientState) {
        stateHash = state.hash
        relayUrl = state.relayUrl
        val isNewUrls = state.urls.isNotEmpty() && state.urls.toSet() != current.value.binding.gatewayUrls.toSet()
        note { binding ->
            binding.copy(
                gatewayUrls = state.urls.ifEmpty { binding.gatewayUrls },
                overlays = state.overlays,
            )
        }
        endRefresh()
        current.update {
            it.copy(
                connection = if (state.isDisabled) HubConnection.WAITING else HubConnection.CONNECTED,
                waitReason = if (state.isDisabled) HubWaitReason.DISABLED else null,
                waitRefusal = null,
                services = state.services,
                terminals = state.terminals,
                reachedThrough = state.reachedThrough,
                isPanelAllowed = state.isPanelAllowed,
            )
        }
        if (isNewUrls) networkChanged()
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
        if (held == HubWaitReason.REPLACED) return hold(HubWaitReason.REPLACED, null)
        return 0
    }

    private fun onUnreachable(refusal: ChannelResult.Refused): Long {
        if (!hasNetwork()) return hold(HubWaitReason.NO_NETWORK, refusal)
        val waitS = backoffS
        backoffS = minOf(backoffS * 2, CLIENT_BACKOFF_MAX_S)
        return waitFor(silentReason(), refusal, waitS)
    }

    private fun onRejected(refusal: ChannelResult.Refused): Long = when (refusal.code) {
        "hub_untrusted" -> waitFor(HubWaitReason.UNTRUSTED, refusal, CLIENT_BACKOFF_MAX_S)
        CLIENT_REFUSAL_CODE_BINDING_UNKNOWN -> hold(HubWaitReason.UNKNOWN_DEVICE, refusal)
        in CLIENT_PROTOCOL_REFUSAL_CODES -> hold(HubWaitReason.TOO_OLD, refusal)
        else -> waitFor(silentReason(), refusal, CLIENT_BACKOFF_MAX_S)
    }

    private fun silentReason(): HubWaitReason =
        if (overlay != null) HubWaitReason.HUB_OFF_OVERLAY else HubWaitReason.HUB_SILENT

    /** Wait [waitS] seconds on [reason], the next round's moment on the view. */
    private fun waitFor(reason: HubWaitReason, refusal: ChannelResult.Refused?, waitS: Long): Long {
        endRefresh()
        log("waiting on ${reason.wireName} for ${waitS}s: ${refusal?.code.orEmpty()} ${refusal?.wordParams.orEmpty()}")
        current.update { it.waiting(reason, refusal, clock() + waitS * 1000) }
        return waitS
    }

    /** Stop the rounds on [reason] until a person, or a network change for `no_network`, starts them. */
    private fun hold(reason: HubWaitReason, refusal: ChannelResult.Refused?): Long {
        held = reason
        endRefresh()
        log("waiting on ${reason.wireName}: ${refusal?.code.orEmpty()} ${refusal?.wordParams.orEmpty()}")
        current.update { it.waiting(reason, refusal, 0) }
        return CLIENT_IDLE_POLL_INTERVAL_S
    }

    private fun HubView.dialling(): HubView = copy(
        connection = HubConnection.CONNECTING,
        waitReason = null,
        waitRefusal = null,
        nextRoundAtMillis = 0,
    )

    private fun HubView.waiting(reason: HubWaitReason, refusal: ChannelResult.Refused?, nextRoundAt: Long): HubView =
        copy(
            connection = HubConnection.WAITING,
            waitReason = reason,
            waitRefusal = refusal,
            nextRoundAtMillis = nextRoundAt,
        )

    private fun unreachable(detail: String) = ChannelResult.refused("hub_unreachable", "detail" to detail)

    private fun nameUrlOf(gatewayUrl: String, address: String): String = try {
        val parts = URI(gatewayUrl)
        val port = if (parts.port > 0) parts.port else CLIENT_HTTPS_DEFAULT_PORT
        "${parts.scheme}://$address:$port"
    } catch (_: URISyntaxException) {
        ""
    }

    private class LiveSocket(
        val socket: ChannelSocket,
        val streams: ChannelStreamRegistry,
        val url: String,
        val events: Channel<ChannelSocketEvent>,
        val openNanos: Long,
    ) {
        /** The nonce of the last ping sent on this socket, empty once its pong was taken. */
        @Volatile
        var pingNonce = ""

        /** When the last ping was sent, in the session's clock. */
        @Volatile
        var pingSentNanos = 0L
    }

    private class DialledSocket(
        val url: String,
        val socket: ChannelSocket,
        val events: Channel<ChannelSocketEvent>,
        val startedNanos: Long,
    ) {
        var openNanos = Long.MAX_VALUE
    }

    /** A dialled socket's first event. */
    private class Dialled(val socket: DialledSocket, val event: ChannelSocketEvent)

    /** A winner of a round beside the channel, welcomed and ready to carry it. */
    private class Moved(val socket: DialledSocket, val welcome: ChannelInbound.Welcome)

    private sealed interface Step {
        class Event(val event: ChannelSocketEvent) : Step

        class Move(val moved: Moved) : Step
    }

    private class Round(
        val winner: DialledSocket?,
        val refusals: List<Pair<String, ChannelResult.Refused>>,
        val isInterrupted: Boolean,
    )

    private sealed interface Handshake {
        data class Welcomed(val welcome: ChannelInbound.Welcome) : Handshake

        data class Rejected(val refusal: ChannelResult.Refused) : Handshake

        data class Failed(val refusal: ChannelResult.Refused) : Handshake
    }
}
