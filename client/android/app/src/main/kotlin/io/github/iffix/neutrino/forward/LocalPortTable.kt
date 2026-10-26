package io.github.iffix.neutrino.forward

import android.content.SharedPreferences
import androidx.core.content.edit
import io.github.iffix.neutrino.CLIENT_SETTINGS_KEY_LOCAL_PORTS
import io.github.iffix.neutrino.FORWARD_FIXED_PORTS
import io.github.iffix.neutrino.FORWARD_PICK_PORTS
import io.github.iffix.neutrino.FORWARD_PROBE_HOST_V4
import io.github.iffix.neutrino.FORWARD_PROBE_HOST_V6
import io.github.iffix.neutrino.FORWARD_PROTOCOL_UDP
import io.github.iffix.neutrino.LocalPortTakenException
import io.github.iffix.neutrino.channel.ChannelResult
import java.io.IOException
import java.net.BindException
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.SocketException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.SerializationException
import kotlinx.serialization.builtins.MapSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.Json

/**
 * The one table of local ports, by entry key `<binding>/<entry>`, kept in the app's settings: the
 * numbers the person set in place of the hub's, and the picks of the forwards of no app, each with
 * its protocol. An app entry listens on the person's number, else the hub's; a forward of no app
 * keeps its pick from 20000 to 23999. A number is probed each time its forward is about to listen:
 * an app entry's number another program holds is refused and never moves by itself, and a kept
 * pick another program now holds is picked again.
 *
 * @param preferences Where the table is written.
 * @param isFree Whether nothing listens on a number on any address of the phone now, by the
 *   number, the protocol and whether the table keeps the number already.
 */
class LocalPortTable(
    private val preferences: SharedPreferences,
    private val isFree: (Int, String, Boolean) -> Boolean = ::isPortFree,
) {
    private val current = MutableStateFlow(read())

    /** Every entry's kept number. */
    val choices: StateFlow<Map<String, LocalPortChoice>> = current.asStateFlow()

    /**
     * The number the person set for an app entry.
     *
     * @param key The entry's key.
     * @return The number, or null when the entry takes the hub's.
     */
    fun numberOf(key: String): Int? = current.value[key]?.takeIf { it.isFixed }?.port

    /**
     * The number an app entry listens on: the person's, else the hub's.
     *
     * @param key The entry's key.
     * @param hubPort The hub's `local_port` for it.
     * @return The number.
     */
    fun portOf(key: String, hubPort: Int): Int = numberOf(key) ?: hubPort

    /**
     * The number an app entry's forward is about to listen on, probed first.
     *
     * @param key The entry's key.
     * @param hubPort The hub's `local_port` for it.
     * @param protocol `tcp` or `udp`.
     * @return The number.
     * @throws LocalPortTakenException When another program holds it.
     */
    fun portForEntry(key: String, hubPort: Int, protocol: String): Int {
        val port = portOf(key, hubPort)
        if (!isFree(port, protocol, true)) throw LocalPortTakenException(port)
        return port
    }

    /**
     * The number a forward of no app is about to listen on: its kept pick while nothing else holds
     * it, else the first free number from 20000 to 23999, kept from then on.
     *
     * @param key The forward's key.
     * @param protocol `tcp` or `udp`.
     * @return The number.
     * @throws IOException When no number is free.
     */
    fun pickFor(key: String, protocol: String): Int = synchronized(this) {
        val kept = current.value[key]?.takeIf { !it.isFixed && it.protocol == protocol }
        if (kept != null && isFree(kept.port, protocol, true)) return kept.port
        val pick = FORWARD_PICK_PORTS.firstOrNull {
            it != kept?.port && !isHeld(it, protocol, key) && isFree(it, protocol, false)
        } ?: throw IOException("no local port is free")
        write(current.value + (key to LocalPortChoice(isFixed = false, port = pick, protocol = protocol)))
        pick
    }

    /**
     * Keep the person's number for an app entry, or go back to the hub's.
     *
     * @param key The entry's key.
     * @param number The number, or null for the hub's.
     * @param protocol `tcp` or `udp`.
     * @param hubNumbers Every app entry's hub number this phone knows, by key, with its protocol.
     * @return Ok once kept, or `port_taken {port}` when another entry of the protocol holds the
     *   number in the table or as its hub number.
     * @throws IllegalArgumentException When the number is outside 1024 to 65535.
     */
    fun configure(
        key: String,
        number: Int?,
        protocol: String,
        hubNumbers: Map<String, Pair<Int, String>>,
    ): ChannelResult<Unit> = synchronized(this) {
        if (number == null) {
            write(current.value - key)
            return ChannelResult.Ok(Unit)
        }
        require(number in FORWARD_FIXED_PORTS) { "a local port is from 1024 to 65535" }
        val isHubHeld = hubNumbers.any { (other, held) ->
            other != key && numberOf(other) == null && held.first == number && held.second == protocol
        }
        if (isHeld(number, protocol, key) || isHubHeld) {
            return ChannelResult.refused("port_taken", "port" to number.toString())
        }
        write(current.value + (key to LocalPortChoice(isFixed = true, port = number, protocol = protocol)))
        ChannelResult.Ok(Unit)
    }

    /**
     * A hub is left: its entries leave the table.
     *
     * @param bindingId The hub.
     */
    fun forget(bindingId: String) = synchronized(this) {
        write(current.value.filterKeys { !it.startsWith("$bindingId/") })
    }

    private fun isHeld(port: Int, protocol: String, key: String): Boolean = current.value.any { (other, choice) ->
        other != key && choice.port == port && choice.protocol == protocol
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
         * the IPv4 wildcard address, then on the IPv6 one where the phone has IPv6, with sockets of
         * the protocol, and closes them. A number the table keeps is probed with address reuse, so
         * the app's own closed connections still lingering on it do not count.
         *
         * @param port The number.
         * @param protocol `tcp` or `udp`.
         * @param isKept Whether the table keeps the number already.
         * @return True when both probes could take it.
         */
        fun isPortFree(port: Int, protocol: String = "tcp", isKept: Boolean = false): Boolean =
            canBind(FORWARD_PROBE_HOST_V4, port, protocol, isKept, isFamilyRequired = true) &&
                canBind(FORWARD_PROBE_HOST_V6, port, protocol, isKept, isFamilyRequired = false)

        private fun canBind(
            host: String,
            port: Int,
            protocol: String,
            isReused: Boolean,
            isFamilyRequired: Boolean,
        ): Boolean = try {
            val address = InetSocketAddress(InetAddress.getByName(host), port)
            if (protocol == FORWARD_PROTOCOL_UDP) {
                DatagramSocket(null).use {
                    it.reuseAddress = isReused
                    it.bind(address)
                }
            } else {
                ServerSocket().use {
                    it.reuseAddress = isReused
                    it.bind(address)
                }
            }
            true
        } catch (_: BindException) {
            false
        } catch (_: SocketException) {
            !isFamilyRequired
        } catch (_: IOException) {
            !isFamilyRequired
        }
    }
}
