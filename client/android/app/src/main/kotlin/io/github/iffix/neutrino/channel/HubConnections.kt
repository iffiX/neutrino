package io.github.iffix.neutrino.channel

import io.github.iffix.neutrino.CLIENT_JOIN_PATH
import io.github.iffix.neutrino.CLIENT_LEAVE_PATH
import io.github.iffix.neutrino.CLIENT_PROTOCOL_REFUSAL_CODES
import io.github.iffix.neutrino.CLIENT_REFUSAL_CODE_BINDING_UNKNOWN
import io.github.iffix.neutrino.binding.BindingStore
import io.github.iffix.neutrino.binding.HubBinding
import java.io.IOException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * One session per hub this phone joined: joining, leaving, and every hub's view.
 *
 * @param store The bindings.
 * @param transport How hubs are reached.
 * @param machine What this phone says about itself.
 * @param resolveHubName The IPv4 address `hub.neutrino.internal` resolves to here, or null.
 * @param scope Where the sessions run.
 */
class HubConnections(
    private val store: BindingStore,
    private val transport: HubTransport,
    private val machine: ClientMachine,
    private val resolveHubName: suspend () -> String?,
    private val scope: CoroutineScope,
) {
    private val sessions = MutableStateFlow<Map<String, HubSession>>(emptyMap())

    /** Every hub's view, in the order joined, each with its binding as the store keeps it now. */
    @OptIn(ExperimentalCoroutinesApi::class)
    val views: Flow<List<HubView>> = sessions.flatMapLatest { held ->
        if (held.isEmpty()) {
            flowOf(emptyList())
        } else {
            combine(held.values.map { it.view }) { it.toList() }
        }
    }.combine(store.bindings) { views, bindings ->
        views.map { view -> bindings.firstOrNull { it.id == view.binding.id }?.let { view.copy(binding = it) } ?: view }
    }

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
            isOverlayWanted = kept?.isOverlayWanted ?: false,
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
                onUnbound = { id -> forget(id) },
            ).also { it.start(scope) }
        }
        sessions.value = next
    }
}
