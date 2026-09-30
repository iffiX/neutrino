package io.github.iffix.neutrino.shell

import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.VpnService
import android.os.PersistableBundle
import androidx.core.net.toUri
import io.github.iffix.neutrino.CLIENT_CLIP_SENSITIVE_EXTRA
import io.github.iffix.neutrino.binding.HubBinding
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.EnrollmentLink
import io.github.iffix.neutrino.channel.HubConnections
import io.github.iffix.neutrino.overlay.OverlayController
import kotlinx.serialization.json.JsonObject

/**
 * The actions over the hub sessions and the phone's own browser and clipboard.
 *
 * @param context The window the actions start activities from.
 * @param connections The hub sessions.
 * @param overlays The virtual network's wish and pick.
 */
class ClientController(
    private val context: Context,
    private val connections: HubConnections,
    private val overlays: OverlayController,
) : ClientActions {
    override suspend fun join(link: String): ChannelResult<HubBinding> =
        when (val parsed = EnrollmentLink.parse(link)) {
            is ChannelResult.Refused -> parsed
            is ChannelResult.Ok -> connections.join(parsed.value)
        }

    override suspend fun leave(bindingId: String): ChannelResult<Unit> = connections.leave(bindingId)

    override suspend fun serviceMaterial(bindingId: String, entryId: String): ChannelResult<JsonObject> {
        val session = connections.session(bindingId) ?: return ChannelResult.refused("unknown_hub")
        return session.openService(entryId)
    }

    override fun reconnect(bindingId: String) {
        connections.session(bindingId)?.reconnect()
    }

    override fun openUrl(url: String) {
        try {
            context.startActivity(Intent(Intent.ACTION_VIEW, url.toUri()))
        } catch (_: ActivityNotFoundException) {
            copy(url)
        }
    }

    override fun copy(text: String, isSecret: Boolean) {
        val clip = ClipData.newPlainText("", text)
        if (isSecret) {
            clip.description.extras = PersistableBundle().apply { putBoolean(CLIENT_CLIP_SENSITIVE_EXTRA, true) }
        }
        context.getSystemService(ClipboardManager::class.java).setPrimaryClip(clip)
    }

    override fun overlayConsent(): Intent? = VpnService.prepare(context)

    override fun setOverlayWanted(bindingId: String, isWanted: Boolean) = overlays.setWanted(bindingId, isWanted)

    override fun pickOverlay(bindingId: String, provider: String) = overlays.pick(bindingId, provider)
}
