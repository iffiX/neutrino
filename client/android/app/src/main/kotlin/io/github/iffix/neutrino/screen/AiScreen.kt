package io.github.iffix.neutrino.screen

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import io.github.iffix.neutrino.CLIENT_KEY_SHOWN_PREFIX
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.ChannelServiceEntry
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.design.AppIcon
import io.github.iffix.neutrino.design.CopyButton
import io.github.iffix.neutrino.design.ErrorLine
import io.github.iffix.neutrino.design.FeatureRow
import io.github.iffix.neutrino.design.IconGlyph
import io.github.iffix.neutrino.design.NeutrinoButton
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.design.QrCodeImage
import io.github.iffix.neutrino.design.ValueField
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * The AI gateway each joined hub publishes: its address and this phone's key to copy, and QR,
 * which draws both for another app to scan.
 *
 * @param hubs Every hub joined.
 * @param material What the hub hands this phone for one entry: `{base_url, api_key, model}`.
 * @param onCopy What copying does, with the text and whether it is a secret.
 */
@Composable
fun AiScreen(
    hubs: List<HubView>,
    material: suspend (String, String) -> ChannelResult<JsonObject>,
    onCopy: (String, Boolean) -> Unit,
) {
    ServiceList(hubs, "ai", "ui.empty_ai") { hub, entry, hasDivider ->
        GatewayRow(hub, entry, hasDivider, material, onCopy)
    }
}

@Composable
private fun GatewayRow(
    hub: HubView,
    entry: ChannelServiceEntry,
    hasDivider: Boolean,
    material: suspend (String, String) -> ChannelResult<JsonObject>,
    onCopy: (String, Boolean) -> Unit,
) {
    val words = NeutrinoTheme.words
    val palette = NeutrinoTheme.palette
    var answer by remember(hub.binding.id, entry.id) { mutableStateOf<ChannelResult<JsonObject>?>(null) }
    var isKeyShown by remember { mutableStateOf(false) }
    var isQrShown by remember { mutableStateOf(false) }
    val isReady = answer is ChannelResult.Ok && !hub.jobs.isRefreshing
    LaunchedEffect(hub.binding.id, entry.id, hub.isConnected) {
        if (hub.isConnected) answer = material(hub.binding.id, entry.id)
    }
    FeatureRow(
        marker = entryTone(hub, entry, isBusy = answer == null),
        hasDivider = hasDivider,
        actions = {
            NeutrinoButton(words.word("ui.qr"), { isQrShown = !isQrShown }, isSmall = true, isEnabled = isReady)
        },
    ) {
        BasicText(words.word("ui.module_ai_gateway"), style = NeutrinoTheme.rowTitle)
        if (entry.isHealthy == false) BasicText(words.word("ui.unhealthy"), style = NeutrinoTheme.note)
        BasicText(entry.text("endpoint"), style = NeutrinoTheme.mono)
        BasicText(providedBy(hub, entry, ""), style = NeutrinoTheme.note)
        when (val current = answer) {
            null -> Unit

            is ChannelResult.Refused -> ErrorLine(current)

            is ChannelResult.Ok -> Column(
                modifier = Modifier.padding(top = 12.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                val baseUrl = current.value.text("base_url").ifEmpty { entry.text("endpoint") }
                val key = current.value.text("api_key")
                ValueField(words.word("ui.gateway_address"), baseUrl) {
                    CopyButton(isEnabled = isReady) { onCopy(baseUrl, false) }
                }
                val shown = if (isKeyShown || key.length <= CLIENT_KEY_SHOWN_PREFIX) {
                    key
                } else {
                    key.take(CLIENT_KEY_SHOWN_PREFIX) + "•".repeat(16)
                }
                ValueField(words.word("ui.client_key"), shown) {
                    RevealToggle(isKeyShown) { isKeyShown = !isKeyShown }
                    CopyButton(isEnabled = isReady) { onCopy(key, true) }
                }
                if (isQrShown) {
                    val code = buildJsonObject {
                        put("base_url", baseUrl)
                        put("api_key", key)
                        put("model", current.value.text("model"))
                    }
                    Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                        QrCodeImage(code.toString(), words.word("ui.ai_qr_label"))
                    }
                    BasicText(
                        words.word("ui.ai_qr_hint"),
                        style = NeutrinoTheme.note.copy(color = palette.textFaint, textAlign = TextAlign.Center),
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            }
        }
    }
}

@Composable
private fun RevealToggle(isShown: Boolean, onToggle: () -> Unit) {
    val words = NeutrinoTheme.words
    val label = words.word(if (isShown) "ui.key_hide" else "ui.key_show")
    Box(
        modifier = Modifier
            .semantics { contentDescription = label }
            .clickable(role = Role.Switch, onClick = onToggle)
            .padding(6.dp),
    ) {
        IconGlyph(if (isShown) AppIcon.EYE_OFF else AppIcon.EYE, NeutrinoTheme.palette.textMuted, size = 16.dp)
    }
}

private fun JsonObject.text(name: String): String = (this[name] as? JsonPrimitive)?.content.orEmpty()

@Preview(widthDp = 400, heightDp = 700)
@Composable
private fun AiScreenPreview() {
    val sample = JsonObject(
        mapOf(
            "base_url" to JsonPrimitive("http://100.72.4.1:8317/v1"),
            "api_key" to JsonPrimitive("sk-nt-7f3a9c21e4b84d06"),
            "model" to JsonPrimitive("gpt-5"),
        ),
    )
    PreviewHubs.Frame(mapOf("ui.gateway_address" to "网关地址", "ui.client_key" to "此客户端的密钥", "ui.copy" to "复制")) {
        AiScreen(PreviewHubs.all, material = { _, _ -> ChannelResult.Ok(sample) }, onCopy = { _, _ -> })
    }
}
