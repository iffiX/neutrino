package io.github.iffix.neutrino.forward

import android.content.SharedPreferences
import androidx.core.content.edit
import io.github.iffix.neutrino.CLIENT_SETTINGS_KEY_LOCAL_PORTS
import io.github.iffix.neutrino.FORWARD_AUTO_FIRST_PORT
import io.github.iffix.neutrino.FORWARD_FIXED_PORTS
import io.github.iffix.neutrino.FORWARD_PROBE_HOST_V4
import io.github.iffix.neutrino.FORWARD_PROBE_HOST_V6
import io.github.iffix.neutrino.LocalPortTakenException
import io.github.iffix.neutrino.PORT_PROTOCOL_TCP
import io.github.iffix.neutrino.PORT_PROTOCOL_UDP
import io.github.iffix.neutrino.channel.ChannelResult
import java.io.IOException
import java.net.BindException
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.SocketAddress
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.SerializationException
import kotlinx.serialization.builtins.MapSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.Json

/**
 * The one table of local ports, by entry key `<binding>/<entry>`, kept in the app's settings:
 * each entry is automatic or fixed and has its protocol, and no two entries of one protocol hold
 * one number, so a TCP entry and a UDP entry can hold the same one. An automatic entry takes
 * its own published port when no other entry holds it and nothing listens on it, else the first
 * free number from 20000 up, and keeps that pick from then on. A kept or fixed number is looked at
 * again each time its forward is about to listen: an automatic pick another program now listens
 * on is picked again and the new number kept, and a fixed one is refused.
 *
 * @param preferences Where the table is written.
 * @param isUdpFree The same for UDP sockets, for a UDP entry.
 * @param isFree Whether nothing listens on a number on any address of the phone now, by the number
 *   and whether the table keeps it for an entry already.
 */
class LocalPortTable(
    private val preferences: SharedPreferences,
    private val isUdpFree: (Int, Boolean) -> Boolean = { port, _ -> isUdpPortFree(port) },
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
     * @param protocol The entry's protocol, `tcp` or `udp`.
     * @return Ok once kept, or `port_taken {port}` when another entry of the same protocol holds the fixed number.
     * @throws IllegalArgumentException When a fixed number is outside 1024 to 65535.
     */
    fun configure(key: String, choice: LocalPortChoice, protocol: String = PORT_PROTOCOL_TCP): ChannelResult<Unit> =
        synchronized(this) {
            if (choice.isFixed) {
                require(choice.port in FORWARD_FIXED_PORTS) { "a fixed local port is from 1024 to 65535" }
                if (isHeld(choice.port, key, protocol)) {
                    return ChannelResult.refused("port_taken", "port" to choice.port.toString())
                }
                write(current.value + (key to choice.copy(protocol = protocol)))
            } else {
                val before = choiceOf(key)
                val kept = if (before.isFixed) LocalPortChoice() else before
                write(current.value + (key to kept.copy(protocol = protocol)))
            }
            ChannelResult.Ok(Unit)
        }

    /**
     * The number an entry's forward is about to listen on: the kept or fixed number while nothing
     * else listens on it, else for an automatic entry a new pick, kept from then on.
     *
     * @param key The entry's key.
     * @param publishedPort The entry's own port.
     * @param protocol The entry's protocol, `tcp` or `udp`; a UDP number is probed with UDP sockets.
     * @return The number.
     * @throws LocalPortTakenException When another program listens on the entry's fixed number.
     * @throws IOException When no number is free.
     */
    fun portFor(key: String, publishedPort: Int, protocol: String = PORT_PROTOCOL_TCP): Int = synchronized(this) {
        val choice = choiceOf(key).copy(protocol = protocol)
        val probe = if (protocol == PORT_PROTOCOL_UDP) isUdpFree else isFree
        if (choice.port != 0) {
            if (probe(choice.port, true)) return choice.port
            if (choice.isFixed) throw LocalPortTakenException(choice.port)
        }
        val isOwnFree = publishedPort in FORWARD_FIXED_PORTS && publishedPort != choice.port &&
            !isHeld(publishedPort, key, protocol) && probe(publishedPort, false)
        val pick = if (isOwnFree) {
            publishedPort
        } else {
            (FORWARD_AUTO_FIRST_PORT..FORWARD_FIXED_PORTS.last).firstOrNull {
                it != choice.port && !isHeld(it, key, protocol) && probe(it, false)
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

    private fun isHeld(port: Int, key: String, protocol: String): Boolean = current.value.any { (other, choice) ->
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

        /**
         * Whether no UDP socket is bound to a number on any address of the phone now: a probe
         * binds a UDP socket on the IPv4 wildcard address, then on the IPv6 one where the phone
         * has IPv6, with no address reuse, and closes it. A UDP number holds no closed
         * connections, so a kept number is probed the same way.
         *
         * @param port The number.
         * @return True when both probes could take it.
         */
        fun isUdpPortFree(port: Int): Boolean = canBindUdp(FORWARD_PROBE_HOST_V4, port, isFamilyRequired = true) &&
            canBindUdp(FORWARD_PROBE_HOST_V6, port, isFamilyRequired = false)

        private fun canBindUdp(host: String, port: Int, isFamilyRequired: Boolean): Boolean = try {
            DatagramSocket(null as SocketAddress?).use {
                it.reuseAddress = false
                it.bind(InetSocketAddress(InetAddress.getByName(host), port))
            }
            true
        } catch (_: BindException) {
            false
        } catch (_: IOException) {
            !isFamilyRequired
        }

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
