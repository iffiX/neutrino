package io.github.iffix.neutrino.shell

import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.VpnService
import android.os.PersistableBundle
import android.provider.DocumentsContract
import androidx.core.net.toUri
import io.github.iffix.neutrino.CLIENT_CLIP_SENSITIVE_EXTRA
import io.github.iffix.neutrino.CLIENT_FILES_AUTHORITY
import io.github.iffix.neutrino.ShareRefusedException
import io.github.iffix.neutrino.ShareUnreachableException
import io.github.iffix.neutrino.binding.HubBinding
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.EnrollmentLink
import io.github.iffix.neutrino.channel.HubConnections
import io.github.iffix.neutrino.files.ShareDocumentId
import io.github.iffix.neutrino.files.ShareLogin
import io.github.iffix.neutrino.files.ShareLoginStore
import io.github.iffix.neutrino.files.ShareRoot
import io.github.iffix.neutrino.files.SmbShareClient
import io.github.iffix.neutrino.overlay.OverlayController
import java.io.IOException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonObject

/**
 * The actions over the hub sessions and the phone's own browser and clipboard.
 *
 * @param context The window the actions start activities from.
 * @param connections The hub sessions.
 * @param overlays The virtual network's wish and pick.
 * @param shares The SMB connections.
 * @param logins The shares' logins.
 */
class ClientController(
    private val context: Context,
    private val connections: HubConnections,
    private val overlays: OverlayController,
    private val shares: SmbShareClient,
    private val logins: ShareLoginStore,
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

    override fun hasShareLogin(rootKey: String): Boolean = logins.get(rootKey) != null

    override suspend fun giveShareLogin(root: ShareRoot, login: ShareLogin, isKept: Boolean): ChannelResult<Unit> =
        withContext(Dispatchers.IO) {
            shares.drop(root.key)
            try {
                shares.list(root, login, ShareDocumentId(root.key, ""))
                logins.put(root.key, login, isKept)
                ChannelResult.Ok(Unit)
            } catch (error: ShareRefusedException) {
                ChannelResult.refused(error.code)
            } catch (_: ShareUnreachableException) {
                ChannelResult.refused("share_unreachable")
            } catch (error: IOException) {
                ChannelResult.refused("client_internal", "error" to (error.message ?: "IOException"))
            }
        }

    override fun openShare(rootKey: String) {
        val root = DocumentsContract.buildRootUri(CLIENT_FILES_AUTHORITY, rootKey)
        val view = Intent(Intent.ACTION_VIEW).setDataAndType(root, DocumentsContract.Root.MIME_TYPE_ITEM)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        try {
            context.startActivity(view)
        } catch (_: ActivityNotFoundException) {
            val pick = Intent(Intent.ACTION_OPEN_DOCUMENT_TREE)
                .putExtra(
                    DocumentsContract.EXTRA_INITIAL_URI,
                    DocumentsContract.buildDocumentUri(CLIENT_FILES_AUTHORITY, "$rootKey/"),
                )
            try {
                context.startActivity(pick)
            } catch (_: ActivityNotFoundException) {
                // The phone has no Files app to show the share in.
            }
        }
    }
}
