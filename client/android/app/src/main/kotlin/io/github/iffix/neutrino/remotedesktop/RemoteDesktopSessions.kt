package io.github.iffix.neutrino.remotedesktop

import android.util.Log
import io.github.iffix.neutrino.CLIENT_LOG_TAG
import io.github.iffix.neutrino.channel.ChannelResult
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject

/**
 * The remote desktop jobs of the app core: a Connect fetching an entry's material, the one
 * viewer open, the code a failed Connect ended in, and the address the hub handed back for the
 * viewer to dial, each by entry key `<binding>/<entry>`.
 *
 * @param material What the hub hands this phone for one entry, by binding id and entry id.
 * @param scope Where the Connect runs.
 * @param choiceOf The codec and quality kept for an entry, by entry key.
 */
class RemoteDesktopSessions(
    private val material: suspend (String, String) -> ChannelResult<JsonObject>,
    private val scope: CoroutineScope,
    private val choiceOf: (String) -> RemoteDesktopChoice = { RemoteDesktopChoice() },
) {
    private val connectingKeys = MutableStateFlow<Set<String>>(emptySet())
    private val failures = MutableStateFlow<Map<String, ChannelResult.Refused>>(emptyMap())
    private val open = MutableStateFlow<Pair<String, RemoteDesktopTarget>?>(null)
    private val addresses = MutableStateFlow<Map<String, String>>(emptyMap())

    /** The address each entry's viewer dials, `host:port` as the hub last handed it back. */
    val dialed: StateFlow<Map<String, String>> = addresses.asStateFlow()

    /** The entries whose Connect runs. */
    val connecting: StateFlow<Set<String>> = connectingKeys.asStateFlow()

    /** The code each entry's last Connect ended in, until its next press or a refresh. */
    val errors: StateFlow<Map<String, ChannelResult.Refused>> = failures.asStateFlow()

    /** The entry key and the target of the viewer open, or null. */
    val viewing: StateFlow<Pair<String, RemoteDesktopTarget>?> = open.asStateFlow()

    /**
     * Press Connect on an entry: its material is fetched and the viewer opens on it with the
     * entry's kept codec and quality. A press
     * while that entry's Connect runs or a viewer is open is dropped.
     *
     * @param bindingId The hub.
     * @param entryId The entry.
     * @param name What the viewer's bar shows.
     * @param platformOs The `platform_os` the entry carries, or empty when it names none.
     */
    fun connect(bindingId: String, entryId: String, name: String, platformOs: String) {
        val key = keyOf(bindingId, entryId)
        if (key in connectingKeys.value || open.value != null) {
            Log.i(CLIENT_LOG_TAG, "a viewer runs or opens; the connect of $key is dropped")
            return
        }
        connectingKeys.update { it + key }
        failures.update { it - key }
        scope.launch {
            when (val target = RemoteDesktopTarget.of(name, material(bindingId, entryId))) {
                is ChannelResult.Refused -> failures.update { it + (key to target) }

                is ChannelResult.Ok -> {
                    addresses.update { it + (key to "${target.value.host}:${target.value.port}") }
                    open.value = key to target.value.copy(choice = choiceOf(key), platformOs = platformOs)
                }
            }
            connectingKeys.update { it - key }
        }
    }

    /** Close the viewer. */
    fun close() {
        open.value = null
    }

    /**
     * A hub is being left: its viewer closes and its addresses go.
     *
     * @param bindingId The hub.
     */
    fun forget(bindingId: String) {
        if (open.value?.first?.startsWith("$bindingId/") == true) open.value = null
        failures.update { errors -> errors.filterKeys { !it.startsWith("$bindingId/") } }
        addresses.update { dialed -> dialed.filterKeys { !it.startsWith("$bindingId/") } }
    }

    /** A refresh: every entry's error goes. */
    fun clearErrors() {
        failures.value = emptyMap()
    }

    companion object {
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
