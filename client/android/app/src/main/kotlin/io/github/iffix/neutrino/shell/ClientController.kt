package io.github.iffix.neutrino.shell

import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.VpnService
import android.provider.DocumentsContract
import android.util.Log
import androidx.core.content.ContextCompat
import androidx.core.net.toUri
import io.github.iffix.neutrino.CLIENT_FILES_AUTHORITY
import io.github.iffix.neutrino.CLIENT_LOG_TAG
import io.github.iffix.neutrino.ConnectRefusedException
import io.github.iffix.neutrino.ShareRefusedException
import io.github.iffix.neutrino.ShareUnreachableException
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.HubConnections
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.files.ShareDocumentId
import io.github.iffix.neutrino.files.ShareLogin
import io.github.iffix.neutrino.files.ShareLoginStore
import io.github.iffix.neutrino.files.ShareRoot
import io.github.iffix.neutrino.files.SmbShareClient
import io.github.iffix.neutrino.forward.PortForwards
import io.github.iffix.neutrino.overlay.OverlayController
import io.github.iffix.neutrino.remotedesktop.RemoteDesktopChoice
import io.github.iffix.neutrino.remotedesktop.RemoteDesktopChoiceStore
import io.github.iffix.neutrino.remotedesktop.RemoteDesktopSessions
import java.io.IOException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * The actions over the app core and the phone's own browser and clipboard.
 *
 * @param context The window the actions start activities from.
 * @param connections The hub sessions.
 * @param overlays The virtual networks.
 * @param desktops The remote desktop Connects and viewer.
 * @param shares The SMB connections.
 * @param logins The shares' logins.
 * @param forwards The loopback forwards.
 * @param desktopChoices Each shared desktop's codec and quality.
 * @param hubs Every hub as the state document holds it now.
 */
class ClientController(
    private val context: Context,
    private val connections: HubConnections,
    private val overlays: OverlayController,
    private val desktops: RemoteDesktopSessions,
    private val shares: SmbShareClient,
    private val logins: ShareLoginStore,
    private val forwards: PortForwards,
    private val desktopChoices: RemoteDesktopChoiceStore,
    private val hubs: () -> List<HubView>,
) : ClientActions {
    override fun join(link: String) = connections.startJoin(link)

    override fun clearJoin() = connections.clearJoin()

    override fun leave(bindingId: String) = connections.startLeave(bindingId)

    override fun reconnect(bindingId: String) {
        connections.session(bindingId)?.reconnect()
    }

    override fun refresh() {
        overlays.clearErrors()
        desktops.clearErrors()
        forwards.clearErrors()
        connections.refresh()
    }

    override fun openUrl(url: String) {
        try {
            context.startActivity(Intent(Intent.ACTION_VIEW, url.toUri()))
        } catch (_: ActivityNotFoundException) {
            copy(url)
        }
    }

    override fun copy(text: String) {
        context.getSystemService(ClipboardManager::class.java).setPrimaryClip(ClipData.newPlainText("", text))
    }

    override fun overlayConsent(): Intent? = VpnService.prepare(context)

    override fun connectOverlay(bindingId: String) = overlays.connect(bindingId)

    override fun cancelOverlay(bindingId: String) = overlays.cancel(bindingId)

    override fun disconnectOverlay(bindingId: String) = overlays.disconnect(bindingId)

    override fun pickOverlay(bindingId: String, provider: String) = overlays.pick(bindingId, provider)

    override fun hasShareLogin(rootKey: String): Boolean = logins.get(rootKey) != null

    override suspend fun giveShareLogin(root: ShareRoot, login: ShareLogin, isKept: Boolean): ChannelResult<Unit> =
        withContext(Dispatchers.IO) {
            shares.drop(root.key)
            try {
                shares.list(root, { login }, ShareDocumentId(root.key, ""))
                logins.put(root.key, login, isKept)
                ChannelResult.Ok(Unit)
            } catch (error: ShareRefusedException) {
                ChannelResult.refused(error.code)
            } catch (_: ShareUnreachableException) {
                ChannelResult.refused("share_unreachable")
            } catch (error: ConnectRefusedException) {
                ChannelResult.Refused(error.code, error.params)
            } catch (error: IOException) {
                ChannelResult.refused("client_internal", "error" to (error.message ?: "IOException"))
            }
        }

    override fun forgetShareLogin(rootKey: String) {
        shares.drop(rootKey)
        try {
            logins.forget(rootKey)
        } catch (_: IOException) {
            Log.w(CLIENT_LOG_TAG, "the kept logins could not be written")
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
                Log.i(CLIENT_LOG_TAG, "the phone has no Files app to show the share in")
            }
        }
    }

    override fun connectDesktop(bindingId: String, entryId: String, name: String, platformOs: String) =
        desktops.connect(bindingId, entryId, name, platformOs)

    override fun remoteDesktopChoiceOf(bindingId: String, entryId: String): RemoteDesktopChoice =
        desktopChoices.get(RemoteDesktopSessions.keyOf(bindingId, entryId))

    override fun configureRemoteDesktop(bindingId: String, entryId: String, choice: RemoteDesktopChoice) =
        desktopChoices.put(RemoteDesktopSessions.keyOf(bindingId, entryId), choice)

    override fun closeDesktop() = desktops.close()

    override fun useApp(bindingId: String, appId: String) {
        val hub = hubs().firstOrNull { it.binding.id == bindingId } ?: return
        val app = hub.apps.firstOrNull { it.id == appId } ?: return
        forwards.use(hub, app, ::openOnMain)
    }

    override fun stopApp(bindingId: String, appId: String) = forwards.stop(bindingId, appId)

    override fun appNumbersOf(bindingId: String, appId: String): Map<String, Int?> {
        val hub = hubs().firstOrNull { it.binding.id == bindingId } ?: return emptyMap()
        return forwards.numbersOf(bindingId, hub.services.filter { it.appId == appId })
    }

    override fun configureApp(bindingId: String, appId: String, numbers: Map<String, Int?>): ChannelResult<Unit> =
        forwards.configure(hubs(), bindingId, appId, numbers)

    override fun openPanel(bindingId: String) {
        val hubId = connections.session(bindingId)?.view?.value?.binding?.hubId.orEmpty()
        forwards.openPanel(bindingId, hubId, ::openOnMain)
    }

    private fun openOnMain(address: String) = ContextCompat.getMainExecutor(context).execute { openUrl(address) }
}
