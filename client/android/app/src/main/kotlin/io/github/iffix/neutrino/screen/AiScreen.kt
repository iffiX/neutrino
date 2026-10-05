package io.github.iffix.neutrino.screen

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import io.github.iffix.neutrino.AI_VERSION_PATH
import io.github.iffix.neutrino.CLIENT_HTTPS_DEFAULT_PORT
import io.github.iffix.neutrino.CLIENT_HTTP_DEFAULT_PORT
import io.github.iffix.neutrino.CLIENT_KEY_SHOWN_PREFIX
import io.github.iffix.neutrino.FORWARD_BIND_HOST
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.ChannelServiceEntry
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.design.ButtonTier
import io.github.iffix.neutrino.design.CopyButton
import io.github.iffix.neutrino.design.ErrorLine
import io.github.iffix.neutrino.design.FeatureRow
import io.github.iffix.neutrino.design.NeutrinoButton
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.design.ReasonLine
import io.github.iffix.neutrino.design.SecretField
import io.github.iffix.neutrino.design.ValueField
import io.github.iffix.neutrino.forward.PortForwardRow
import io.github.iffix.neutrino.forward.PortForwards
import java.net.URI
import java.net.URISyntaxException
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * The AI gateway each joined hub publishes, forwarded as a Ports row: Connect makes the forward
 * on this phone's loopback through the hub, the forwarded row shows two loopback addresses, for
 * apps that add `/v1` themselves and for apps that want it in the address, each with its own Copy,
 * and under them sits this phone's key with its eye toggle and Copy. A line
 * says an app on the phone reaches the gateway only while this app runs.
 *
 * @param hubs Every hub joined.
 * @param forwards Each entry's forward, by entry key.
 * @param material What the hub hands this phone for one entry: `{api_key, model}`.
 * @param onConnect What pressing Connect does, with the binding id, the entry id and the gateway's port.
 * @param onDisconnect What pressing Disconnect does, with the binding id and the entry id.
 * @param onCopy What copying does, with the text and whether it is a secret.
 */
@Composable
fun AiScreen(
    hubs: List<HubView>,
    forwards: Map<String, PortForwardRow>,
    material: suspend (String, String) -> ChannelResult<JsonObject>,
    onConnect: (String, String, Int) -> Unit,
    onDisconnect: (String, String) -> Unit,
    onCopy: (String, Boolean) -> Unit,
) {
    ServiceList(hubs, "ai", "ui.empty_ai") { hub, entry, hasDivider ->
        val row = forwards[PortForwards.keyOf(hub.binding.id, entry.id)] ?: PortForwardRow()
        GatewayRow(hub, entry, row, hasDivider, material, onConnect, onDisconnect, onCopy)
    }
}

/**
 * The two addresses an app on the phone points at while the gateway is forwarded: one for an app
 * that adds `/v1` itself, one for an app that wants it in the address.
 *
 * @param endpoint The entry's endpoint, where the gateway stands on the hub's networks.
 * @param localPort The forward's loopback number.
 * @return `http://127.0.0.1:<local port><path of the endpoint>`, then the same with `/v1` after
 *   it unless the path already ends in `/v1`.
 */
internal fun loopbackAddressesOf(endpoint: String, localPort: Int): List<String> {
    val plain = "http://$FORWARD_BIND_HOST:$localPort${endpointPartsOf(endpoint)?.second.orEmpty()}"
    val trimmed = plain.trimEnd('/')
    return listOf(plain, if (trimmed.endsWith(AI_VERSION_PATH)) trimmed else trimmed + AI_VERSION_PATH)
}

/**
 * The gateway's own port and path, from its endpoint.
 *
 * @param endpoint The entry's endpoint.
 * @return The port, by the scheme when the address names none, and the path; null when the address cannot be read.
 */
internal fun endpointPartsOf(endpoint: String): Pair<Int, String>? = try {
    val address = URI(endpoint)
    val port = when {
        address.port > 0 -> address.port
        address.scheme == "https" -> CLIENT_HTTPS_DEFAULT_PORT
        else -> CLIENT_HTTP_DEFAULT_PORT
    }
    if (address.host.isNullOrEmpty()) null else port to address.rawPath.orEmpty()
} catch (_: URISyntaxException) {
    null
}

@Composable
private fun GatewayRow(
    hub: HubView,
    entry: ChannelServiceEntry,
    row: PortForwardRow,
    hasDivider: Boolean,
    material: suspend (String, String) -> ChannelResult<JsonObject>,
    onConnect: (String, String, Int) -> Unit,
    onDisconnect: (String, String) -> Unit,
    onCopy: (String, Boolean) -> Unit,
) {
    val words = NeutrinoTheme.words
    var answer by remember(hub.binding.id, entry.id) { mutableStateOf<ChannelResult<JsonObject>?>(null) }
    var isKeyShown by remember { mutableStateOf(false) }
    val endpoint = entry.text("endpoint")
    val port = endpointPartsOf(endpoint)?.first
    val job = row.job
    val isHealthy = entry.isHealthy != false
    val isFree = job == null && !hub.jobs.isRefreshing && !hub.isDisabled
    val reason = when {
        job != null || hub.jobs.isRefreshing -> null
        hub.isDisabled -> words.word("ui.reason.disabled")
        !isHealthy && !row.isForwarded -> words.word("ui.reason.unhealthy")
        else -> null
    }
    LaunchedEffect(hub.binding.id, entry.id, hub.isConnected) {
        if (hub.isConnected) answer = material(hub.binding.id, entry.id)
    }
    FeatureRow(
        marker = entryTone(hub, entry, isBusy = job != null || answer == null),
        hasDivider = hasDivider,
        actions = {
            NeutrinoButton(
                label = words.word(
                    when {
                        job != null -> job.wordKey
                        row.isForwarded -> "ui.port_disconnect"
                        else -> "ui.port_connect"
                    },
                ),
                onClick = {
                    if (row.isForwarded) {
                        onDisconnect(hub.binding.id, entry.id)
                    } else if (port != null) {
                        onConnect(hub.binding.id, entry.id, port)
                    }
                },
                tier = if (row.isForwarded && job == null) ButtonTier.DANGER else ButtonTier.PLAIN,
                isEnabled = isFree && port != null && (isHealthy || row.isForwarded),
                isBusy = job != null,
                isSmall = true,
            )
        },
    ) {
        BasicText(words.word("ui.module_ai_gateway"), style = NeutrinoTheme.rowTitle)
        if (!isHealthy) BasicText(words.word("ui.unhealthy"), style = NeutrinoTheme.note)
        val forwarded = if (row.isForwarded) {
            " → " + words.word("ui.forwarding_to", mapOf("port" to row.localPort))
        } else {
            ""
        }
        BasicText(endpoint + forwarded, style = NeutrinoTheme.mono)
        BasicText(providedBy(hub, entry, ""), style = NeutrinoTheme.note)
        BasicText(words.word("ui.ai_needs_client"), style = NeutrinoTheme.note)
        ErrorLine(row.error)
        ReasonLine(reason)
        if (row.isForwarded) {
            val (plain, withVersion) = loopbackAddressesOf(endpoint, row.localPort)
            Column(modifier = Modifier.padding(top = 12.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                ValueField(words.word("ui.ai_address_plain"), plain) {
                    CopyButton(isEnabled = isFree) { onCopy(plain, false) }
                }
                ValueField(words.word("ui.ai_address_v1"), withVersion) {
                    CopyButton(isEnabled = isFree) { onCopy(withVersion, false) }
                }
            }
        }
        when (val current = answer) {
            null -> Unit

            is ChannelResult.Refused -> ErrorLine(current)

            is ChannelResult.Ok -> Column(
                modifier = Modifier.padding(top = 12.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                val key = (current.value["api_key"] as? JsonPrimitive)?.content.orEmpty()
                val shown = if (isKeyShown || key.length <= CLIENT_KEY_SHOWN_PREFIX) {
                    key
                } else {
                    key.take(CLIENT_KEY_SHOWN_PREFIX) + "•".repeat(16)
                }
                SecretField(words.word("ui.client_key"), shown, isKeyShown, onToggle = { isKeyShown = !isKeyShown }) {
                    CopyButton(isEnabled = !hub.jobs.isRefreshing) { onCopy(key, true) }
                }
            }
        }
    }
}

@Preview(widthDp = 400, heightDp = 700)
@Composable
private fun AiScreenPreview() {
    val sample = JsonObject(
        mapOf("api_key" to JsonPrimitive("sk-nt-7f3a9c21e4b84d06"), "model" to JsonPrimitive("gpt-5")),
    )
    PreviewHubs.Frame(mapOf("ui.client_key" to "此客户端的密钥", "ui.copy" to "复制", "ui.port_connect" to "连接")) {
        AiScreen(
            PreviewHubs.all,
            emptyMap(),
            material = { _, _ -> ChannelResult.Ok(sample) },
            onConnect = { _, _, _ -> },
            onDisconnect = { _, _ -> },
            onCopy = { _, _ -> },
        )
    }
}
