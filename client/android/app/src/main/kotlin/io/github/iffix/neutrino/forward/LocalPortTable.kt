package io.github.iffix.neutrino.forward

import android.content.SharedPreferences
import androidx.core.content.edit
import io.github.iffix.neutrino.CLIENT_SETTINGS_KEY_LOCAL_PORTS
import io.github.iffix.neutrino.FORWARD_AUTO_FIRST_PORT
import io.github.iffix.neutrino.FORWARD_FIXED_PORTS
import io.github.iffix.neutrino.FORWARD_PROBE_HOST_V4
import io.github.iffix.neutrino.FORWARD_PROBE_HOST_V6
import io.github.iffix.neutrino.LocalPortTakenException
import io.github.iffix.neutrino.channel.ChannelResult
import java.io.IOException
import java.net.BindException
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.SerializationException
import kotlinx.serialization.builtins.MapSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.Json

/**
 * The one table of local ports, by entry key `<binding>/<entry>`, kept in the app's settings:
 * each entry is automatic or fixed, and no two entries hold one number. An automatic entry takes
 * its own published port when no other entry holds it and nothing listens on it, else the first
 * free number from 20000 up, and keeps that pick from then on. A kept or fixed number is looked at
 * again each time its forward is about to listen: an automatic pick another program now listens
 * on is picked again and the new number kept, and a fixed one is refused.
 *
 * @param preferences Where the table is written.
 * @param isFree Whether nothing listens on a number on any address of the phone now, by the number
 *   and whether the table keeps it for an entry already.
 */
class LocalPortTable(
    private val preferences: SharedPreferences,
    private val isFree: (Int, Boolean) -> Boolean = ::isPortFree,
) {
    private val current = MutableStateFlow(read())

    /** Every entry's choice. */
    val choices: StateFlow<Map<String, LocalPortChoice>> = current.asStateFlow()

    /**
     * One entry's choice.
     *
     * @param key The entry's key.
     * @return The choice; automatic with no pick for an entry the table does not hold.
     */
    fun choiceOf(key: String): LocalPortChoice = current.value[key] ?: LocalPortChoice()

    /**
     * Keep the person's choice for one entry. Automatic keeps the entry's pick when it was
     * automatic already.
     *
     * @param key The entry's key.
     * @param choice Automatic, or fixed with its number.
     * @return Ok once kept, or `port_taken {port}` when another entry holds the fixed number.
     * @throws IllegalArgumentException When a fixed number is outside 1024 to 65535.
     */
    fun configure(key: String, choice: LocalPortChoice): ChannelResult<Unit> = synchronized(this) {
        if (choice.isFixed) {
            require(choice.port in FORWARD_FIXED_PORTS) { "a fixed local port is from 1024 to 65535" }
            if (isHeld(choice.port, key)) return ChannelResult.refused("port_taken", "port" to choice.port.toString())
            write(current.value + (key to choice))
        } else {
            val before = choiceOf(key)
            write(current.value + (key to if (before.isFixed) LocalPortChoice() else before))
        }
        ChannelResult.Ok(Unit)
    }

    /**
     * The number an entry's forward is about to listen on: the kept or fixed number while nothing
     * else listens on it, else for an automatic entry a new pick, kept from then on.
     *
     * @param key The entry's key.
     * @param publishedPort The entry's own port.
     * @return The number.
     * @throws LocalPortTakenException When another program listens on the entry's fixed number.
     * @throws IOException When no number is free.
     */
    fun portFor(key: String, publishedPort: Int): Int = synchronized(this) {
        val choice = choiceOf(key)
        if (choice.port != 0) {
            if (isFree(choice.port, true)) return choice.port
            if (choice.isFixed) throw LocalPortTakenException(choice.port)
        }
        val isOwnFree = publishedPort in FORWARD_FIXED_PORTS && publishedPort != choice.port &&
            !isHeld(publishedPort, key) && isFree(publishedPort, false)
        val pick = if (isOwnFree) {
            publishedPort
        } else {
            (FORWARD_AUTO_FIRST_PORT..FORWARD_FIXED_PORTS.last).firstOrNull {
                it != choice.port && !isHeld(it, key) && isFree(it, false)
            } ?: throw IOException("no local port is free")
        }
        write(current.value + (key to choice.copy(port = pick)))
        pick
    }

    /**
     * A hub is left: its entries leave the table.
     *
     * @param bindingId The hub.
     */
    fun forget(bindingId: String) = synchronized(this) {
        write(current.value.filterKeys { !it.startsWith("$bindingId/") })
    }

    private fun isHeld(port: Int, key: String): Boolean = current.value.any { (other, choice) ->
        other != key && choice.port == port
    }

    private fun write(table: Map<String, LocalPortChoice>) {
        preferences.edit { putString(CLIENT_SETTINGS_KEY_LOCAL_PORTS, json.encodeToString(serializer, table)) }
        current.value = table
    }

    private fun read(): Map<String, LocalPortChoice> {
        val text = preferences.getString(CLIENT_SETTINGS_KEY_LOCAL_PORTS, null) ?: return emptyMap()
        return try {
            json.decodeFromString(serializer, text)
        } catch (_: SerializationException) {
            emptyMap()
        } catch (_: IllegalArgumentException) {
            emptyMap()
        }
    }

    companion object {
        private val json = Json { ignoreUnknownKeys = true }
        private val serializer = MapSerializer(String.serializer(), LocalPortChoice.serializer())

        /**
         * Whether nothing listens on a number on any address of the phone now: a probe binds it on
         * the IPv4 wildcard address, then on the IPv6 one where the phone has IPv6, and closes it.
         * A new pick is probed with no address reuse. A number the table keeps is probed with
         * address reuse, so the app's own closed connections still lingering on it do not count,
         * while another program's listener still does.
         *
         * @param port The number.
         * @param isKept Whether the table keeps the number for an entry already.
         * @return True when both probes could take it.
         */
        fun isPortFree(port: Int, isKept: Boolean = false): Boolean =
            canBind(FORWARD_PROBE_HOST_V4, port, isKept, isFamilyRequired = true) &&
                canBind(FORWARD_PROBE_HOST_V6, port, isKept, isFamilyRequired = false)

        private fun canBind(host: String, port: Int, isReused: Boolean, isFamilyRequired: Boolean): Boolean = try {
            ServerSocket().use {
                it.reuseAddress = isReused
                it.bind(InetSocketAddress(InetAddress.getByName(host), port))
            }
            true
        } catch (_: BindException) {
            false
        } catch (_: IOException) {
            !isFamilyRequired
        }
    }
}
