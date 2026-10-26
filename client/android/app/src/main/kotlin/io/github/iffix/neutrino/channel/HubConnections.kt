package io.github.iffix.neutrino.channel

import android.util.Log
import io.github.iffix.neutrino.CLIENT_ADDRESS_SCHEME
import io.github.iffix.neutrino.CLIENT_LEAVE_TELL_TIMEOUT_S
import io.github.iffix.neutrino.CLIENT_LOG_TAG
import io.github.iffix.neutrino.CLIENT_PRIVATE_KEY_BYTES
import io.github.iffix.neutrino.CLIENT_ROLE
import io.github.iffix.neutrino.PROTOCOL
import io.github.iffix.neutrino.binding.BindingStore
import io.github.iffix.neutrino.binding.HubBinding
import io.github.iffix.neutrino.transport.ClientTransport
import java.io.IOException
import java.security.SecureRandom
import java.util.UUID
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * One session per hub this phone joined: joining, leaving, refreshing, and every hub's view.
 *
 * @param store The bindings.
 * @param transport The transport's local channel.
 * @param machine What this phone says about itself.
 * @param resolveHubName The IPv4 address `hub.neutrino.internal` resolves to here, or null.
 * @param scope Where the sessions and the jobs run.
 * @param hasNetwork Whether the phone has a network at all.
 * @param onLeaving Called with a binding's id as its leave starts: its network and viewers stop.
 */
class HubConnections(
    private val store: BindingStore,
    private val transport: ClientTransport,
    private val machine: ClientMachine,
    private val resolveHubName: suspend () -> String?,
    private val scope: CoroutineScope,
    private val hasNetwork: () -> Boolean = { true },
    private val onLeaving: (String) -> Unit = {},
) {
    private val sessions = MutableStateFlow<Map<String, HubSession>>(emptyMap())
    private val leaving = MutableStateFlow<Set<String>>(emptySet())
    private val jobErrors = MutableStateFlow<Map<String, ChannelResult.Refused>>(emptyMap())
    private val joining = MutableStateFlow(HubJoin())
    private val replacing = Any()

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

    /** The join a person started from the Join page. */
    val join: StateFlow<HubJoin> = joining.asStateFlow()

    /**
     * Run one session per binding, following the store as bindings come and go. Of two or more bindings holding
     * one hub id, the one joined last is kept and each other one ends as at a leave, its hub told.
     */
    fun start() {
        val dropped = try {
            store.dropRepeatedHubs()
        } catch (error: IOException) {
            Log.w(CLIENT_LOG_TAG, "could not forget the repeated bindings here", error)
            emptyList()
        }
        for (held in dropped) {
            Log.i(CLIENT_LOG_TAG, "dropped the binding ${held.id}: a later one holds its hub")
            onLeaving(held.id)
            if (isTold(held)) scope.launch { tellLeft(held) }
        }
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
     * Refresh every hub that can be: each one's error line goes, and each hub is asked again.
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
     * Keep the binding a link names, its ticket unspent and a static key made for it: the hub's
     * session spends the ticket with the transport's `join`. A link whose ticket a binding already
     * holds is that binding.
     *
     * @param link The link.
     * @return The binding kept, or `client_internal {error}` when the file cannot be written.
     */
    fun join(link: EnrollmentLink): ChannelResult<HubBinding> {
        store.bindings.value.firstOrNull { it.ticket == link.ticket }?.let { return ChannelResult.Ok(it) }
        val binding = HubBinding(
            id = UUID.randomUUID().toString().replace("-", ""),
            name = machine.hostname,
            gatewayUrl = link.urls.first(),
            gatewayUrls = link.urls,
            hubKey = link.hubKey,
            privateKey = freshPrivateKey(),
            token = "",
            ticket = link.ticket,
            overlays = link.overlays,
        )
        return try {
            store.put(binding)
            ChannelResult.Ok(binding)
        } catch (error: IOException) {
            ChannelResult.refused("client_internal", "error" to (error.message ?: "IOException"))
        }
    }

    /**
     * Start leaving one hub; the row shows the leave until this phone has forgotten the binding,
     * which never waits on the hub. A second press while the leave runs is dropped.
     *
     * @param bindingId The binding's id.
     */
    fun startLeave(bindingId: String) {
        if (bindingId in leaving.value) {
            Log.i(CLIENT_LOG_TAG, "a leave of $bindingId is running; the second press is dropped")
            return
        }
        Log.i(CLIENT_LOG_TAG, "leaving the hub of $bindingId: its binding is forgotten now")
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
     * Leave one hub: this phone forgets the binding at once, then tells the hub once in the
     * background through the transport's `leave`, within the short timeout, and the hub's answer
     * changes nothing. A binding whose ticket is unspent, or of 0.5's shape, is only forgotten.
     *
     * @param bindingId The binding's id.
     * @return Ok once forgotten, or `client_internal {error}` when the file cannot be written.
     */
    fun leave(bindingId: String): ChannelResult<Unit> {
        val binding = store.get(bindingId) ?: return ChannelResult.Ok(Unit)
        val forgotten = forget(bindingId)
        if (forgotten is ChannelResult.Ok && isTold(binding)) scope.launch { tellLeft(binding) }
        return forgotten
    }

    /** The app came back to the foreground: every hub with no open socket runs a round now. */
    fun resume() {
        sessions.value.values.forEach { it.resume() }
    }

    /** The phone's network changed: every session runs a round now. */
    fun networkChanged() {
        sessions.value.values.forEach { it.networkChanged() }
    }

    private fun forget(bindingId: String): ChannelResult<Unit> = try {
        store.remove(bindingId)
        ChannelResult.Ok(Unit)
    } catch (error: IOException) {
        ChannelResult.refused("client_internal", "error" to (error.message ?: "IOException"))
    }

    private suspend fun tellLeft(binding: HubBinding) {
        val addresses = (listOf(binding.gatewayUrl) + binding.storedUrls)
            .filter { it.startsWith("$CLIENT_ADDRESS_SCHEME://") }
            .distinct()
        val fields = buildJsonObject {
            put("binding", binding.id)
            put("hub_key", binding.hubKey)
            put("private_key", binding.privateKey)
            put("psk", binding.psk)
            put("role", CLIENT_ROLE)
            put("protocol", PROTOCOL)
            put("addresses", JsonArray(addresses.map { JsonPrimitive(it) }))
        }
        val outcome = when (val answer = transport.command("leave", fields, CLIENT_LEAVE_TELL_TIMEOUT_S * 1000)) {
            is ChannelResult.Ok -> "ok"
            is ChannelResult.Refused -> answer.code
        }
        Log.i(CLIENT_LOG_TAG, "the hub of ${binding.id} answered the leave: $outcome")
    }

    private fun isTold(binding: HubBinding): Boolean = !binding.isPending && !binding.isKeyMissing

    private fun joined(bindingId: String, hubBindingId: String) =
        replace(bindingId, isTold = false) { it.boundId == hubBindingId }

    private fun welcomed(bindingId: String, hubId: String) {
        if (hubId.isNotEmpty()) replace(bindingId, isTold = true) { it.hubId == hubId }
    }

    private fun replace(bindingId: String, isTold: Boolean, isSameHub: (HubBinding) -> Boolean) {
        synchronized(replacing) {
            if (store.get(bindingId) == null) return
            for (held in store.bindings.value.filter { it.id != bindingId && isSameHub(it) }) {
                Log.i(CLIENT_LOG_TAG, "the join replaced the binding ${held.id} held here")
                onLeaving(held.id)
                if (forget(held.id) is ChannelResult.Ok && isTold && isTold(held)) scope.launch { tellLeft(held) }
            }
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
                onJoined = ::joined,
                onWelcomed = ::welcomed,
                hasNetwork = hasNetwork,
            ).also { it.start(scope) }
        }
        sessions.value = next
    }

    private companion object {
        fun freshPrivateKey(): String {
            val bytes = ByteArray(CLIENT_PRIVATE_KEY_BYTES)
            SecureRandom().nextBytes(bytes)
            return bytes.joinToString("") { "%02x".format(it) }
        }
    }
}
