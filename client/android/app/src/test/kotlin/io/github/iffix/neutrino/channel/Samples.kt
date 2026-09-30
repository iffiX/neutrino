package io.github.iffix.neutrino.channel

import io.github.iffix.neutrino.binding.HubBinding
import java.util.Base64
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.add
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/** Sample values the channel tests share. */
object Samples {
    /** A fingerprint of the right shape. */
    val FINGERPRINT = "ab".repeat(32)

    /** This phone. */
    val machine = ClientMachine(
        machineId = "0f".repeat(16),
        hostname = "pixel",
        arch = "arm64",
        osVersion = "15",
        version = "0.5.0",
    )

    /** A binding to one hub at two addresses. */
    val binding = HubBinding(
        id = "b1",
        name = "pixel",
        gatewayUrl = "https://192.168.100.1:8443",
        gatewayUrls = listOf("https://192.168.100.1:8443", "https://100.72.4.1:8443"),
        fingerprint = FINGERPRINT,
        token = "secret-token",
    )

    /**
     * A link over one payload.
     *
     * @param payload The object.
     * @param isPadded Whether the base64 keeps its `=` padding.
     * @return The link.
     */
    fun link(payload: JsonObject, isPadded: Boolean = false): String {
        val encoder = if (isPadded) Base64.getUrlEncoder() else Base64.getUrlEncoder().withoutPadding()
        return "neutrino://enroll/" + encoder.encodeToString(payload.toString().toByteArray())
    }

    /** A client link with a NetBird and an EasyTier console object. */
    val clientPayload: JsonObject = buildJsonObject {
        put(
            "urls",
            buildJsonArray {
                add("https://192.168.100.1:8443/")
                add("https://100.72.4.1:8443")
            },
        )
        put("token", "ticket-1")
        put("fp", FINGERPRINT.uppercase())
        put("role", "client")
        put(
            "overlays",
            buildJsonArray {
                add(
                    buildJsonObject {
                        put("provider", "netbird")
                        put("setup_key", "KEY")
                        put("management_url", "")
                        put("fqdn", "hub.netbird.cloud")
                    },
                )
                add(
                    buildJsonObject {
                        put("provider", "easytier")
                        put("mode", "console")
                        put("config_server", "tcp://et.example:22020/token")
                        put("is_secure_mode", true)
                        put("hub_address", "10.126.126.1")
                    },
                )
                add(buildJsonObject { put("provider", "wireguard") })
            },
        )
    }
}
