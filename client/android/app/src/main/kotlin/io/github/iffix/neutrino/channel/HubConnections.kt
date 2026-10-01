package io.github.iffix.neutrino.channel

import android.util.Log
import io.github.iffix.neutrino.CLIENT_JOIN_PATH
import io.github.iffix.neutrino.CLIENT_LEAVE_PATH
import io.github.iffix.neutrino.CLIENT_LOG_TAG
import io.github.iffix.neutrino.CLIENT_NOTICE_SHOWN_S
import io.github.iffix.neutrino.CLIENT_PROTOCOL_REFUSAL_CODES
import io.github.iffix.neutrino.CLIENT_REFUSAL_CODE_BINDING_UNKNOWN
import io.github.iffix.neutrino.binding.BindingStore
import io.github.iffix.neutrino.binding.HubBinding
import java.io.IOException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * One session per hub this phone joined: joining, leaving, refreshing, and every hub's view.
 *
 * @param store The bindings.
 * @param transport How hubs are reached.
 * @param machine What this phone says about itself.
 * @param resolveHubName The IPv4 address `hub.neutrino.internal` resolves to here, or null.
 * @param scope Where the sessions and the jobs run.
 * @param onLeaving Called with a binding's id as its leave starts: its network and viewers stop.
 */
class HubConnections(
    private val store: BindingStore,
    private val transport: HubTransport,
    private val machine: ClientMachine,
    private val resolveHubName: suspend () -> String?,
    private val scope: CoroutineScope,
    private val onLeaving: (String) -> Unit = {},
) {
    private val sessions = MutableStateFlow<Map<String, HubSession>>(emptyMap())
    private val leaving = MutableStateFlow<Set<String>>(emptySet())
    private val jobErrors = MutableStateFlow<Map<String, ChannelResult.Refused>>(emptyMap())
    private val noticeList = MutableStateFlow<List<HubNotice>>(emptyList())
    private val joining = MutableStateFlow(HubJoin())

    /** Every hub's view, in the order joined, each with its binding as the store keeps it now and its leave. */
    @OptIn(ExperimentalCoroutinesApi::class)
    val views: Flow<List<HubView>> = sessions.flatMapLatest { held ->
        if (held.isEmpty()) {
            flowOf(emptyList())
        } else {
            combine(held.values.map { it.view }) { it.toList() }
        }
    }.combine(store.bindings) { views, bindings ->
        views.map { view -> bindings.firstOrNull { it.id == view.binding.id }?.let { view.copy(binding = it) } ?: view }
    }.combine(combine(leaving, jobErrors) { left, errors -> left to errors }) { views, (left, errors) ->
        views.map { view ->
            val id = view.binding.id
            view.copy(jobs = view.jobs.copy(isLeaving = id in left), jobError = errors[id])
        }
    }

    /** The hubs that no longer know this phone, each shown for a minute after its row went. */
    val notices: StateFlow<List<HubNotice>> = noticeList.asStateFlow()

    /** The join a person started from the Join page. */
    val join: StateFlow<HubJoin> = joining.asStateFlow()

    /** Run one session per binding, following the store as bindings come and go. */
    fun start() {
        scope.launch { store.bindings.collect { follow(it) } }
    }

    /**
     * The session of one binding.
     *
     * @param bindingId The binding's id.
     * @return The session, or null.
     */
    fun session(bindingId: String): HubSession? = sessions.value[bindingId]

    /**
     * Refresh every hub that can be: each one's error line goes, and each is asked again.
     *
     * @return Whether any hub entered refreshing.
     */
    fun refresh(): Boolean {
        jobErrors.value = emptyMap()
        return sessions.value.values.map { it.refresh() }.any { it }
    }

    /**
     * Start joining the hub a pasted or scanned link names; [join] says how it goes.
     *
     * @param text The link's text.
     */
    fun startJoin(text: String) {
        if (joining.value.isJoining) {
            Log.i(CLIENT_LOG_TAG, "a join is running; the second press is dropped")
            return
        }
        joining.value = HubJoin(isJoining = true)
        scope.launch {
            val answer = when (val parsed = EnrollmentLink.parse(text)) {
                is ChannelResult.Refused -> parsed
                is ChannelResult.Ok -> join(parsed.value)
            }
            joining.value = when (answer) {
                is ChannelResult.Ok -> HubJoin(joinedId = answer.value.id)
                is ChannelResult.Refused -> HubJoin(refusal = answer)
            }
        }
    }

    /** The Join page has drawn the join's end: it is forgotten. */
    fun clearJoin() {
        if (!joining.value.isJoining) joining.value = HubJoin()
    }

    /**
     * Join the hub a link names: every address is tried until one answers with the pinned certificate.
     *
     * @param link The link.
     * @return The binding kept, or the refusal: the two protocol codes with `{peer, hub, min}`,
     *   `enroll_refused` for a spent or foreign ticket, `hub_untrusted {url}` for another
     *   certificate, `enroll_no_token` for an answer without an id or a token, `hub_unreachable
     *   {detail, urls}` when no address answered.
     */
    suspend fun join(link: EnrollmentLink): ChannelResult<HubBinding> {
        val body = ChannelFrames.joinRequest(link.ticket, machine)
        var lastFailure = ""
        for (url in link.urls) {
            when (val answer = transport.post(url, CLIENT_JOIN_PATH, link.fingerprint, body)) {
                is ChannelResult.Ok -> return keep(link, url, answer.value)

                is ChannelResult.Refused -> when {
                    answer.code in CLIENT_PROTOCOL_REFUSAL_CODES || answer.code == "hub_untrusted" -> return answer
                    answer.code == "hub_unreachable" -> lastFailure = answer.wordParams["detail"].orEmpty()
                    else -> return ChannelResult.refused("enroll_refused")
                }
            }
        }
        return ChannelResult.refused(
            "hub_unreachable",
            "detail" to lastFailure,
            "urls" to link.urls.joinToString(", "),
        )
    }

    /**
     * Start leaving one hub; the row shows the leave until the hub answers. A second press while
     * the leave runs is dropped.
     *
     * @param bindingId The binding's id.
     */
    fun startLeave(bindingId: String) {
        if (bindingId in leaving.value) {
            Log.i(CLIENT_LOG_TAG, "a leave of $bindingId is running; the second press is dropped")
            return
        }
        leaving.update { it + bindingId }
        jobErrors.update { it - bindingId }
        onLeaving(bindingId)
        scope.launch {
            val answer = leave(bindingId)
            leaving.update { it - bindingId }
            if (answer is ChannelResult.Refused) jobErrors.update { it + (bindingId to answer) }
        }
    }

    /**
     * Leave one hub: the hub revokes the binding, and this phone forgets it.
     *
     * @param bindingId The binding's id.
     * @return Ok once forgotten, or the refusal that kept the binding.
     */
    suspend fun leave(bindingId: String): ChannelResult<Unit> {
        val binding = store.get(bindingId) ?: return ChannelResult.Ok(Unit)
        var refusal: ChannelResult.Refused = ChannelResult.refused("hub_unreachable")
        for (url in binding.candidateUrls("")) {
            when (
                val answer = transport.post(
                    url,
                    CLIENT_LEAVE_PATH,
                    binding.fingerprint,
                    ChannelFrames.leaveRequest(binding),
                )
            ) {
                is ChannelResult.Ok -> return forget(bindingId)

                is ChannelResult.Refused -> {
                    if (answer.code == CLIENT_REFUSAL_CODE_BINDING_UNKNOWN) return forget(bindingId)
                    refusal = answer
                    if (answer.code != "hub_unreachable") break
                }
            }
        }
        return refusal
    }

    /** The phone's network changed: every session runs a round now. */
    fun networkChanged() {
        sessions.value.values.forEach { it.networkChanged() }
    }

    private fun keep(link: EnrollmentLink, url: String, answer: JsonObject): ChannelResult<HubBinding> {
        val id = (answer["id"] as? JsonPrimitive)?.content.orEmpty()
        val token = (answer["token"] as? JsonPrimitive)?.content.orEmpty()
        if (id.isEmpty() || token.isEmpty()) return ChannelResult.refused("enroll_no_token")
        val kept = store.get(id)
        val binding = HubBinding(
            id = id,
            name = machine.hostname,
            gatewayUrl = url,
            gatewayUrls = link.urls,
            fingerprint = link.fingerprint,
            token = token,
            overlays = link.overlays,
            isOverlayOn = kept?.isOverlayOn ?: false,
            overlayChoice = kept?.overlayChoice.orEmpty(),
        )
        return try {
            store.put(binding)
            ChannelResult.Ok(binding)
        } catch (error: IOException) {
            ChannelResult.refused("client_internal", "error" to (error.message ?: "IOException"))
        }
    }

    private fun forget(bindingId: String): ChannelResult<Unit> = try {
        store.remove(bindingId)
        ChannelResult.Ok(Unit)
    } catch (error: IOException) {
        ChannelResult.refused("client_internal", "error" to (error.message ?: "IOException"))
    }

    private fun unbound(bindingId: String, refusal: ChannelResult.Refused) {
        val title = store.get(bindingId)?.title.orEmpty()
        onLeaving(bindingId)
        forget(bindingId)
        val notice = HubNotice(title, refusal)
        noticeList.update { it + notice }
        scope.launch {
            delay(CLIENT_NOTICE_SHOWN_S * 1000)
            noticeList.update { it - notice }
        }
    }

    private fun follow(bindings: List<HubBinding>) {
        val held = sessions.value
        val wanted = bindings.map { it.id }.toSet()
        held.filterKeys { it !in wanted }.values.forEach { it.stop() }
        val next = LinkedHashMap<String, HubSession>()
        for (binding in bindings) {
            next[binding.id] = held[binding.id] ?: HubSession(
                bindingId = binding.id,
                store = store,
                transport = transport,
                machine = machine,
                resolveHubName = resolveHubName,
                onUnbound = ::unbound,
            ).also { it.start(scope) }
        }
        sessions.value = next
    }
}
