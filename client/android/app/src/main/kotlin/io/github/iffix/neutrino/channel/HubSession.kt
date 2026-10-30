package io.github.iffix.neutrino.channel

import android.os.SystemClock
import android.util.Log
import io.github.iffix.neutrino.CLIENT_ADDRESS_SCHEME
import io.github.iffix.neutrino.CLIENT_BACKOFF_MAX_S
import io.github.iffix.neutrino.CLIENT_BACKOFF_MIN_S
import io.github.iffix.neutrino.CLIENT_CONNECT_TIMEOUT_S
import io.github.iffix.neutrino.CLIENT_HUB_ROLE
import io.github.iffix.neutrino.CLIENT_LOG_TAG
import io.github.iffix.neutrino.CLIENT_PING_INTERVAL_S
import io.github.iffix.neutrino.CLIENT_PROTOCOL_REFUSAL_CODES
import io.github.iffix.neutrino.CLIENT_REFRESH_TIMEOUT_S
import io.github.iffix.neutrino.CLIENT_REFUSAL_CODE_ADMISSION_PAUSED
import io.github.iffix.neutrino.CLIENT_REFUSAL_CODE_BINDING_UNKNOWN
import io.github.iffix.neutrino.CLIENT_REFUSAL_CODE_CONTROL_UNAVAILABLE
import io.github.iffix.neutrino.CLIENT_REFUSAL_CODE_REPLACED
import io.github.iffix.neutrino.CLIENT_REFUSAL_LOG_INTERVAL_S
import io.github.iffix.neutrino.CLIENT_REPORT_INTERVAL_S
import io.github.iffix.neutrino.CLIENT_ROLE
import io.github.iffix.neutrino.CLIENT_ROUND_RETRIED_CODES
import io.github.iffix.neutrino.CLIENT_ROUND_SILENT_CODES
import io.github.iffix.neutrino.CLIENT_STREAM_TIMEOUT_S
import io.github.iffix.neutrino.PROTOCOL
import io.github.iffix.neutrino.TRANSPORT_JOIN_TIMEOUT_S
import io.github.iffix.neutrino.binding.BindingStore
import io.github.iffix.neutrino.binding.HubBinding
import io.github.iffix.neutrino.transport.ClientTransport
import io.github.iffix.neutrino.transport.TransportEvent
import io.github.iffix.neutrino.transport.TransportStream
import java.io.IOException
import java.net.URI
import java.net.URISyntaxException
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import kotlin.math.roundToLong
import kotlin.time.Duration.Companion.nanoseconds
import kotlin.time.DurationUnit
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonObjectBuilder
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put

/**
 * One hub's channel, run by the transport the app embeds: the binding's ticket spent with the
 * transport's `join`, then `dial` with every candidate address and its path, the `hello` on each
 * session the transport opens, the state taken and the reports sent, and the row's state from the
 * transport's events.
 *
 * A round dials the hub's address on the virtual network that is on, the address the hub's name
 * resolves to, and the binding's addresses, each with the path it reaches the hub by. The view is
 * `connecting` while a round dials, `connected` from the `welcome`, and `waiting` with a
 * [HubWaitReason] otherwise, counting down to the next round the transport names. Every address
 * failing waits as `hub_silent`, or `hub_off_overlay` while this phone is on the hub's virtual
 * network, or as `no_network` while the phone has no network; `hub_untrusted` waits 60 s;
 * `binding_unknown`, a protocol refusal and `replaced` wait for a person. A session that ends with
 * no refusal is dialled again at once by the transport. A session the transport moved to a better
 * path is greeted again, and the channel stays connected. The live session sends a `ping` frame
 * every 20 s and once after each welcome, and the `pong` echoing its nonce sets the view's `rttMs`.
 *
 * A binding whose ticket is unspent spends it with the transport's `join`; a refusal of the
 * ticket is `join_refused` with its code, and no round runs after it, except `admission_paused`:
 * the ticket is kept, and the join runs again after the `retry_after_s` it names. A binding of
 * 0.5's shape, with no hub key, is `join_refused` with `hub_key_missing` and dials nothing.
 *
 * @param bindingId The binding the session is for, and the name the transport knows it by.
 * @param store Where the binding is kept and noted.
 * @param transport The transport's local channel.
 * @param machine What this phone says about itself.
 * @param resolveHubName The IPv4 address `hub.neutrino.internal` resolves to here, or null.
 * @param onJoined Called with the binding's id and the hub's id for it once its ticket is spent.
 * @param onWelcomed Called with the binding's id and the hub id after each welcome, before the binding
 *   takes that id and before the session's first state is read.
 * @param clock The time in milliseconds, stamped on the view when the live session ends and for the next round.
 * @param localNetworks The networks this phone holds an address in, read for each candidate's path.
 * @param nanoClock The time in nanoseconds, by which each ping's round trip is measured.
 * @param hasNetwork Whether the phone has a network at all, read when a round ended with no session.
 * @param writeLog Writes one log line.
 * @throws IllegalArgumentException When the store holds no binding with [bindingId].
 */
class HubSession(
    val bindingId: String,
    private val store: BindingStore,
    private val transport: ClientTransport,
    private val machine: ClientMachine,
    private val resolveHubName: suspend () -> String?,
    private val onJoined: (String, String) -> Unit = { _, _ -> },
    private val onWelcomed: (String, String) -> Unit = { _, _ -> },
    private val clock: () -> Long = System::currentTimeMillis,
    private val localNetworks: () -> List<ChannelLocalNetwork> = ChannelPath::deviceNetworks,
    private val nanoClock: () -> Long = SystemClock::elapsedRealtimeNanos,
    private val hasNetwork: () -> Boolean = { true },
    private val writeLog: (String) -> Unit = { Log.i(CLIENT_LOG_TAG, it) },
) {
    private val current = MutableStateFlow(HubView(requireNotNull(store.get(bindingId))))
    private val news = Channel<Unit>(Channel.CONFLATED)
    private val requests = ConcurrentHashMap<String, CompletableDeferred<ChannelResult<JsonObject>>>()
    private var job: Job? = null
    private var scope: CoroutineScope? = null
    private var refreshTimer: Job? = null
    private var countdown: Job? = null
    private var liveJobs: Job? = null
    private var backoffS = CLIENT_BACKOFF_MIN_S
    private var stateHash = ""
    private var sessionAddress = ""
    private var dialled: List<ChannelCandidate>? = null

    // The control_unavailable refusals since the line at unavailableLoggedAtMillis. It is null outside a run.
    private var unavailableCount = 0
    private var unavailableLoggedAtMillis: Long? = null

    @Volatile
    private var held: HubWaitReason? = null

    @Volatile
    private var isLive = false

    @Volatile
    private var isJoining = false

    @Volatile
    private var overlay: ChannelOverlayRoute? = null

    @Volatile
    private var serverUrls: Map<ChannelPath, String> = emptyMap()

    @Volatile
    private var pingNonce = ""

    @Volatile
    private var pingSentNanos = 0L

    /** The hub as the screens read it. */
    val view: StateFlow<HubView> = current.asStateFlow()

    /**
     * Join and dial the hub, and follow the transport's events until [stop].
     *
     * @param scope Where the session's work and the refresh's timer run.
     */
    fun start(scope: CoroutineScope) {
        this.scope = scope
        if (job != null) return
        val events = transport.subscribe(bindingId)
        job = scope.launch {
            val binding = store.get(bindingId) ?: return@launch
            if (binding.isKeyMissing) {
                hold(HubWaitReason.JOIN_REFUSED, ChannelResult.refused("hub_key_missing"))
                return@launch
            }
            if (binding.isPending && !join()) return@launch
            dial(isForced = true)
            for (event in events) take(event)
        }
    }

    /** Stop following the hub, and tell the transport to dial it no more. */
    fun stop() {
        job?.cancel()
        job = null
        refreshTimer?.cancel()
        countdown?.cancel()
        endLive()
        transport.unsubscribe(bindingId)
        scope?.launch { transport.command("undial", fields()) }
    }

    /** Take the binding back from a client that replaced this one, and dial now. */
    fun reconnect() {
        if (held != HubWaitReason.REPLACED) return
        held = null
        backoffS = CLIENT_BACKOFF_MIN_S
        current.update { it.dialling() }
        scope?.launch { dial(isForced = true) }
    }

    /**
     * A network changed: a virtual network of the hub's turned on or its peer list changed, the
     * phone's connectivity changed, or the hub's state named other addresses. A hub that waits for
     * a person, or the hub's admission, runs nothing; any other hub dials its candidates again and
     * starts a round now, beside the live session when there is one, with the backoff at its floor.
     */
    fun networkChanged() {
        when (held) {
            null -> Unit
            HubWaitReason.NO_NETWORK -> held = null
            else -> return
        }
        val reason = current.value.waitReason
        if (reason == HubWaitReason.DISABLED || reason == HubWaitReason.ADMISSION_PAUSED) return
        backoffS = CLIENT_BACKOFF_MIN_S
        if (isJoining) {
            news.trySend(Unit)
            return
        }
        scope?.launch { roundNow() }
    }

    /** The app came back to the foreground: a hub with no live session runs a round now, as on a network change. */
    fun resume() {
        if (!isLive) networkChanged()
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
        if (route != null && route != previous) {
            networkChanged()
        } else if (route == null && previous != null) {
            scope?.launch { dial() }
        }
    }

    /**
     * A person pressed refresh: the hub is asked again. A connected hub gets a report with
     * `is_refresh`; a hub with no live session runs a round now. A replaced or disabled hub, or one
     * that waits only for Leave, takes no refresh. The refresh ends on a state frame, a code, or after 10 s.
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
        if (isLive) {
            report(isRefresh = true)
        } else {
            if (held == HubWaitReason.TOO_OLD || held == HubWaitReason.NO_NETWORK) held = null
            backoffS = CLIENT_BACKOFF_MIN_S
            if (isJoining) news.trySend(Unit) else scope?.launch { roundNow() }
        }
        return true
    }

    /**
     * Open one stream on the live session, on a local connection of its own. Blocks until the hub answers.
     *
     * @param open The stream's `open` record, `{kind, ...args}`.
     * @return The stream, or the refusal; `hub_unreachable` while the hub is not connected.
     */
    fun openStream(open: JsonObject): ChannelResult<TransportStream> {
        if (!isLive) return ChannelResult.refused("hub_unreachable", "detail" to "this hub is not connected")
        return transport.open(bindingId, open)
    }

    /**
     * The material one published entry takes from the hub: the reply to a `service` frame.
     *
     * @param entryId The entry's id.
     * @return The reply's params, or its refusal.
     */
    suspend fun openService(entryId: String): ChannelResult<JsonObject> =
        openService(ChannelFrames.args("id" to entryId))

    /**
     * What the hub hands this phone on a `service` frame: an entry's material for `{id}`, the
     * panel's one-time `{token}` for `{is_panel: true}`. The material is logged nowhere.
     *
     * @param args The frame's arguments.
     * @return The reply's params, or its refusal.
     */
    suspend fun openService(args: Map<String, JsonElement>): ChannelResult<JsonObject> =
        ask { ChannelFrames.service(it, args) }

    /**
     * Set whether a kept shell stays and whether others can attach to it.
     *
     * @param sessionId The session.
     * @param isPersistent Whether it outlives every window.
     * @param isShared Whether every client with terminal rights on the machine lists it.
     * @return The reply, or its refusal.
     */
    suspend fun persist(sessionId: String, isPersistent: Boolean, isShared: Boolean): ChannelResult<JsonObject> =
        ask { ChannelFrames.persist(it, sessionId, isPersistent, isShared) }

    /**
     * End a kept shell and every program in it.
     *
     * @param sessionId The session.
     * @return The reply, or its refusal.
     */
    suspend fun stopSession(sessionId: String): ChannelResult<JsonObject> =
        ask { ChannelFrames.stopSession(it, sessionId) }

    private suspend fun ask(frameOf: (String) -> JsonObject): ChannelResult<JsonObject> {
        if (!isLive) return ChannelResult.refused("hub_unreachable", "detail" to "this hub is not connected")
        val request = UUID.randomUUID().toString()
        val answer = CompletableDeferred<ChannelResult<JsonObject>>()
        requests[request] = answer
        val frame = frameOf(request)
        if (!transport.frame(bindingId, frame)) {
            requests.remove(request)
            return ChannelResult.refused("hub_unreachable", "detail" to "the transport is gone")
        }
        val got = withTimeoutOrNull(CLIENT_STREAM_TIMEOUT_S * 1000) { answer.await() }
        requests.remove(request)
        val result = got ?: ChannelResult.refused("hub_unreachable", "detail" to "the hub did not answer")
        if (result is ChannelResult.Refused) log("the hub refused a ${frame.text("type")}: ${result.code}")
        return result
    }

    /**
     * Spend the binding's ticket with the transport's `join`, again after each wait, until the hub
     * takes it or refuses it.
     *
     * @return Whether the binding now holds its token.
     */
    private suspend fun join(): Boolean {
        isJoining = true
        try {
            while (true) {
                val binding = store.get(bindingId) ?: return false
                if (!binding.isPending) return true
                news.tryReceive()
                current.update { it.dialling() }
                val fields = buildJsonObject {
                    put("binding", bindingId)
                    put("hub_key", binding.hubKey)
                    put("private_key", binding.privateKey)
                    put("addresses", JsonArray(candidates(binding).map { JsonPrimitive(it.address) }))
                    ChannelFrames.join(binding.ticket, machine).forEach { (name, value) -> put(name, value) }
                }
                val waitS = when (val answer = transport.command("join", fields, TRANSPORT_JOIN_TIMEOUT_S * 1000)) {
                    is ChannelResult.Ok -> {
                        if (spend(answer.value)) return true
                        hold(HubWaitReason.JOIN_REFUSED, ChannelResult.refused("enroll_no_token"))
                        return false
                    }

                    is ChannelResult.Refused -> when (answer.code) {
                        "hub_untrusted" -> waitFor(HubWaitReason.UNTRUSTED, answer, CLIENT_BACKOFF_MAX_S)

                        CLIENT_REFUSAL_CODE_ADMISSION_PAUSED ->
                            waitFor(HubWaitReason.ADMISSION_PAUSED, answer, retryAfterS(answer))

                        in CLIENT_ROUND_SILENT_CODES -> silent(answer, null)

                        in CLIENT_ROUND_RETRIED_CODES -> waitFor(silentReason(), answer, retryAfterS(answer))

                        else -> {
                            hold(HubWaitReason.JOIN_REFUSED, answer)
                            return false
                        }
                    }
                }
                withTimeoutOrNull(waitS * 1000) { news.receive() }
            }
        } finally {
            isJoining = false
        }
    }

    private fun spend(answer: JsonObject): Boolean {
        val id = answer.text("binding_id")
        val token = answer.text("token")
        if (id.isEmpty() || token.isEmpty()) return false
        val kept = try {
            store.update(bindingId) { it.copy(hubBindingId = id, token = token, ticket = "") }
        } catch (error: IOException) {
            log("the joined binding could not be written: ${error.message}")
            null
        } ?: return false
        current.update { it.copy(binding = kept) }
        log("joined the hub as $id")
        onJoined(bindingId, id)
        return true
    }

    /**
     * Give the transport the hub's candidates; unchanged candidates are not sent again unless forced.
     *
     * @param isForced Whether the `dial` goes even with the candidates it last named.
     */
    private suspend fun dial(isForced: Boolean = false) {
        val binding = store.get(bindingId) ?: return
        if (binding.isPending || binding.isKeyMissing || held == HubWaitReason.REPLACED) return
        val candidates = candidates(binding)
        if (!isForced && candidates == dialled) return
        dialled = candidates
        val fields = fields {
            put("hub_key", binding.hubKey)
            put("private_key", binding.privateKey)
            put("psk", binding.psk)
            put("role", CLIENT_ROLE)
            put("protocol", PROTOCOL)
            put(
                "candidates",
                JsonArray(
                    candidates.map {
                        buildJsonObject {
                            put("address", it.address)
                            put("path", it.path)
                        }
                    },
                ),
            )
        }
        val answer = transport.command("dial", fields)
        if (answer is ChannelResult.Refused) {
            dialled = null
            log("the transport did not take the dial: ${answer.code}")
            if (!isLive) {
                val waitS = silent(answer, null)
                countdown = scope?.launch {
                    delay(waitS * 1000)
                    dial(isForced = true)
                }
            }
        }
    }

    private suspend fun roundNow() {
        dial()
        transport.command("round", fields())
    }

    private suspend fun take(event: TransportEvent) {
        when (event) {
            is TransportEvent.SessionOpen -> open(event)

            is TransportEvent.Frame -> takeFrame(event.frame)

            is TransportEvent.RoundEnd -> roundEnded(event)

            is TransportEvent.SessionEnd -> sessionEnded(event.refusal)

            TransportEvent.Restarted -> {
                endLive()
                current.update { it.dialling() }
                dial(isForced = true)
            }
        }
    }

    private fun open(event: TransportEvent.SessionOpen) {
        val binding = store.get(bindingId) ?: return
        if (held == HubWaitReason.TOO_OLD || held == HubWaitReason.NO_NETWORK) held = null
        sessionAddress = event.address
        val isMove = isLive
        log(
            if (isMove) {
                "the channel moves to ${event.address} (${event.path}) after a ${event.handshakeMs} ms handshake"
            } else {
                "a session opened at ${event.address} (${event.path}) after a ${event.handshakeMs} ms handshake"
            },
        )
        transport.frame(bindingId, ChannelFrames.hello(binding, machine))
    }

    private fun takeFrame(frame: JsonObject) {
        val inbound = try {
            ChannelInbound.decode(frame)
        } catch (error: IllegalArgumentException) {
            log("a frame the hub sent does not read: ${error.message.orEmpty()}")
            return
        }
        when (inbound) {
            is ChannelInbound.Welcome -> if (inbound.role == CLIENT_HUB_ROLE) welcome(inbound)

            is ChannelInbound.State -> {
                takeState(inbound.state)
                report()
            }

            is ChannelInbound.Reply -> requests.remove(inbound.request)?.complete(inbound.result)

            is ChannelInbound.Pong -> takePong(inbound.nonce)

            is ChannelInbound.Refused -> refused(inbound.refusal)

            is ChannelInbound.Unknown -> Unit
        }
    }

    private fun welcome(welcome: ChannelInbound.Welcome) {
        if (unavailableLoggedAtMillis != null) {
            val refused = if (unavailableCount > 0) {
                "; refused $CLIENT_REFUSAL_CODE_CONTROL_UNAVAILABLE $unavailableCount times since the last line"
            } else {
                ""
            }
            log("the hub welcomed this client$refused")
            unavailableCount = 0
            unavailableLoggedAtMillis = null
        }
        onWelcomed(bindingId, welcome.id)
        isLive = true
        backoffS = CLIENT_BACKOFF_MIN_S
        countdown?.cancel()
        note {
            it.copy(gatewayUrl = sessionAddress.ifEmpty { it.gatewayUrl }, hubId = welcome.id, hubName = welcome.name)
        }
        current.update {
            it.copy(
                connection = HubConnection.CONNECTED,
                waitReason = if (it.waitReason == HubWaitReason.DISABLED) it.waitReason else null,
                waitRefusal = null,
                nextRoundAtMillis = 0,
                software = welcome.software,
                connectedAddress = sessionAddress,
                hasConnected = true,
                droppedAtMillis = 0,
            )
        }
        report(isRefresh = current.value.jobs.isRefreshing)
        ping()
        if (liveJobs == null) {
            liveJobs = scope?.launch {
                launch {
                    while (isActive) {
                        delay(CLIENT_REPORT_INTERVAL_S * 1000)
                        report()
                    }
                }
                launch {
                    while (isActive) {
                        delay(CLIENT_PING_INTERVAL_S * 1000)
                        ping()
                    }
                }
            }
        }
    }

    private fun refused(refusal: ChannelResult.Refused) {
        log("the hub refused the session: ${refusal.code}")
        when (refusal.code) {
            CLIENT_REFUSAL_CODE_REPLACED -> held = HubWaitReason.REPLACED
            CLIENT_REFUSAL_CODE_BINDING_UNKNOWN -> held = HubWaitReason.UNKNOWN_DEVICE
            in CLIENT_PROTOCOL_REFUSAL_CODES -> held = HubWaitReason.TOO_OLD
            else -> Unit
        }
    }

    private fun roundEnded(event: TransportEvent.RoundEnd) {
        val refusal = event.refusal ?: ChannelResult.refused("hub_unreachable")
        endRefresh()
        when (refusal.code) {
            "hub_untrusted" -> waitFor(HubWaitReason.UNTRUSTED, refusal, event.nextRoundS)
            CLIENT_REFUSAL_CODE_BINDING_UNKNOWN -> hold(HubWaitReason.UNKNOWN_DEVICE, refusal)
            CLIENT_REFUSAL_CODE_REPLACED -> hold(HubWaitReason.REPLACED, refusal)
            in CLIENT_PROTOCOL_REFUSAL_CODES -> hold(HubWaitReason.TOO_OLD, refusal)
            else -> silent(refusal, event.nextRoundS)
        }
    }

    private fun sessionEnded(refusal: ChannelResult.Refused?) {
        endLive()
        when {
            refusal?.code == CLIENT_REFUSAL_CODE_REPLACED || held == HubWaitReason.REPLACED ->
                hold(HubWaitReason.REPLACED, refusal)

            refusal?.code == CLIENT_REFUSAL_CODE_BINDING_UNKNOWN || held == HubWaitReason.UNKNOWN_DEVICE ->
                hold(HubWaitReason.UNKNOWN_DEVICE, refusal)

            refusal != null && (refusal.code in CLIENT_PROTOCOL_REFUSAL_CODES || held == HubWaitReason.TOO_OLD) ->
                hold(HubWaitReason.TOO_OLD, refusal)

            refusal != null -> waitFor(silentReason(), refusal, retryAfterS(refusal))

            else -> current.update { it.dialling() }
        }
    }

    private fun endLive() {
        isLive = false
        liveJobs?.cancel()
        liveJobs = null
        pingNonce = ""
        val gone = requests.values.toList()
        requests.clear()
        gone.forEach { it.complete(ChannelResult.refused("hub_unreachable", "detail" to "the session ended")) }
        current.update {
            if (it.connectedAddress.isEmpty() && it.connection != HubConnection.CONNECTED) {
                it
            } else {
                it.copy(
                    connection = HubConnection.CONNECTING,
                    connectedAddress = "",
                    droppedAtMillis = clock(),
                    rttMs = null,
                    waitReason = if (it.waitReason == HubWaitReason.DISABLED) null else it.waitReason,
                )
            }
        }
    }

    private fun ping() {
        val nonce = UUID.randomUUID().toString()
        pingSentNanos = nanoClock()
        pingNonce = nonce
        transport.frame(bindingId, ChannelFrames.ping(nonce))
    }

    private fun takePong(nonce: String) {
        if (nonce.isEmpty() || nonce != pingNonce) return
        pingNonce = ""
        val rttMs = (nanoClock() - pingSentNanos).nanoseconds.toDouble(DurationUnit.MILLISECONDS).roundToLong()
        current.update { it.copy(rttMs = rttMs) }
    }

    private fun takeState(state: ChannelClientState) {
        stateHash = state.hash
        serverUrls = state.serverUrls
        val isNewUrls = state.urls.isNotEmpty() && state.urls.toSet() != current.value.binding.gatewayUrls.toSet()
        note { binding ->
            binding.copy(gatewayUrls = state.urls.ifEmpty { binding.gatewayUrls }, overlays = state.overlays)
        }
        endRefresh()
        current.update {
            it.copy(
                connection = if (state.isDisabled) HubConnection.WAITING else HubConnection.CONNECTED,
                waitReason = if (state.isDisabled) HubWaitReason.DISABLED else null,
                waitRefusal = null,
                services = state.services,
                apps = state.apps,
                terminals = state.terminals,
                reachedThrough = state.reachedThrough,
                isPanelAllowed = state.isPanelAllowed,
            )
        }
        if (isNewUrls) networkChanged()
    }

    private fun report(isRefresh: Boolean = false): Boolean =
        transport.frame(bindingId, ChannelFrames.report(stateHash, machine, isRefresh))

    private suspend fun candidates(binding: HubBinding): List<ChannelCandidate> {
        val stored = binding.storedUrls.filter { schemeOf(it) == CLIENT_ADDRESS_SCHEME }
        val nameUrl = stored.firstOrNull()?.let { first -> resolveHubName()?.let { addressOn(first, it) } }.orEmpty()
        val route = overlay
        val networks = localNetworks()
        return (listOf(route?.url.orEmpty(), nameUrl) + stored)
            .filter { it.isNotEmpty() }
            .distinct()
            .map { ChannelCandidate(it, ChannelPath.of(it, route, serverUrls, networks).wireName) }
    }

    private fun fields(more: JsonObjectBuilder.() -> Unit = {}): JsonObject = buildJsonObject {
        put("binding", bindingId)
        more()
    }

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

    /**
     * Every address of a round failed: `no_network` with no countdown while the phone has none,
     * else `hub_silent` or `hub_off_overlay` until the next round.
     *
     * @param refusal The code the round ended in.
     * @param nextRoundS The seconds the transport names to its next round; null to count down the
     *   backoff, which then doubles.
     * @return The seconds waited.
     */
    private fun silent(refusal: ChannelResult.Refused, nextRoundS: Long?): Long {
        if (!hasNetwork()) {
            hold(HubWaitReason.NO_NETWORK, refusal)
            return CLIENT_CONNECT_TIMEOUT_S
        }
        val waitS = nextRoundS ?: backoffS.also { backoffS = minOf(backoffS * 2, CLIENT_BACKOFF_MAX_S) }
        return waitFor(silentReason(), refusal, waitS)
    }

    private fun silentReason(): HubWaitReason =
        if (overlay != null) HubWaitReason.HUB_OFF_OVERLAY else HubWaitReason.HUB_SILENT

    /** The refusal's `retry_after_s`, else [CLIENT_BACKOFF_MAX_S], and at least a second. */
    private fun retryAfterS(refusal: ChannelResult.Refused): Long =
        ((refusal.params["retry_after_s"] as? JsonPrimitive)?.longOrNull ?: CLIENT_BACKOFF_MAX_S).coerceAtLeast(1)

    /** Wait [waitS] seconds on [reason], the next round's moment on the view, and show `connecting` at 0. */
    private fun waitFor(reason: HubWaitReason, refusal: ChannelResult.Refused?, waitS: Long): Long {
        endRefresh()
        logWait(reason, refusal, waitS)
        val nextAt = if (waitS > 0) clock() + waitS * 1000 else 0
        current.update { it.waiting(reason, refusal, nextAt) }
        countdown?.cancel()
        if (waitS > 0) {
            countdown = scope?.launch {
                delay(waitS * 1000)
                current.update { if (it.nextRoundAtMillis == nextAt && !isLive) it.dialling() else it }
            }
        }
        return waitS
    }

    /** Stop on [reason] until a person, or a network change for `no_network`, starts the rounds again. */
    private fun hold(reason: HubWaitReason, refusal: ChannelResult.Refused?) {
        held = reason
        endRefresh()
        countdown?.cancel()
        log("waiting on ${reason.wireName}: ${refusal?.code.orEmpty()}")
        current.update { it.waiting(reason, refusal, 0) }
    }

    /**
     * Log a wait. A wait after `control_unavailable` writes its line at the first refusal, then at most once every
     * [CLIENT_REFUSAL_LOG_INTERVAL_S] with the count since the line before.
     */
    private fun logWait(reason: HubWaitReason, refusal: ChannelResult.Refused?, waitS: Long) {
        val line = "waiting on ${reason.wireName} for ${waitS}s: ${refusal?.code.orEmpty()}"
        if (refusal?.code != CLIENT_REFUSAL_CODE_CONTROL_UNAVAILABLE) {
            log(line)
            return
        }
        unavailableCount += 1
        val now = clock()
        val loggedAt = unavailableLoggedAtMillis
        if (loggedAt != null && now - loggedAt < CLIENT_REFUSAL_LOG_INTERVAL_S * 1000) return
        val count = unavailableCount
        unavailableCount = 0
        unavailableLoggedAtMillis = now
        log(if (loggedAt == null) line else "$line, $count times since the last line")
    }

    private fun log(text: String) {
        writeLog("hub ${current.value.binding.title}: $text")
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

    private fun JsonObject.text(name: String): String = (this[name] as? JsonPrimitive)?.content.orEmpty()

    private companion object {
        fun schemeOf(url: String): String = try {
            URI(url).scheme.orEmpty().lowercase()
        } catch (_: URISyntaxException) {
            ""
        }

        fun addressOn(url: String, address: String): String = try {
            val parts = URI(url)
            "${parts.scheme}://$address:${parts.port}"
        } catch (_: URISyntaxException) {
            ""
        }
    }
}
