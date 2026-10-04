package io.github.iffix.neutrino.shell

import android.content.Intent
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.HubNotice
import io.github.iffix.neutrino.files.ShareLogin
import io.github.iffix.neutrino.files.ShareRoot
import io.github.iffix.neutrino.forward.LocalPortChoice
import io.github.iffix.neutrino.remotedesktop.RemoteDesktopChoice
import kotlinx.serialization.json.JsonObject

/**
 * What a person can do from a screen. An action that starts a job writes the job into the app
 * core's state before it returns; the screens draw what the state then says.
 */
interface ClientActions {
    /**
     * Start joining the hub a pasted or scanned link names.
     *
     * @param link The link's text.
     */
    fun join(link: String)

    /** The Join page has drawn the join's end. */
    fun clearJoin()

    /**
     * Start leaving one hub.
     *
     * @param bindingId The binding's id.
     */
    fun leave(bindingId: String)

    /**
     * Take a hub's binding back from a socket that replaced this one.
     *
     * @param bindingId The binding's id.
     */
    fun reconnect(bindingId: String)

    /** Refresh every hub, and drop every error line and every notice. */
    fun refresh()

    /**
     * Take one notice off the Hubs page.
     *
     * @param notice The notice.
     */
    fun closeNotice(notice: HubNotice)

    /**
     * The material one published entry takes from its hub.
     *
     * @param bindingId The hub's binding.
     * @param entryId The entry's id.
     * @return The material, or the refusal to word.
     */
    suspend fun serviceMaterial(bindingId: String, entryId: String): ChannelResult<JsonObject>

    /**
     * Open an address in the phone's browser.
     *
     * @param url The address.
     */
    fun openUrl(url: String)

    /**
     * Put text on the clipboard.
     *
     * @param text The text.
     * @param isSecret Whether the phone should keep it out of its clipboard preview.
     */
    fun copy(text: String, isSecret: Boolean = false)

    /**
     * What the phone asks before the app may run a VPN.
     *
     * @return The consent screen to show, or null once the person has consented.
     */
    fun overlayConsent(): Intent?

    /**
     * Press Connect on a hub's virtual network.
     *
     * @param bindingId The hub.
     */
    fun connectOverlay(bindingId: String)

    /**
     * Press Cancel on a hub's virtual network while it connects.
     *
     * @param bindingId The hub.
     */
    fun cancelOverlay(bindingId: String)

    /**
     * Press Disconnect on a hub's virtual network.
     *
     * @param bindingId The hub.
     */
    fun disconnectOverlay(bindingId: String)

    /**
     * Pick which of a hub's virtual networks the next connect joins.
     *
     * @param bindingId The hub.
     * @param provider The network's provider.
     */
    fun pickOverlay(bindingId: String, provider: String)

    /**
     * Whether a share has a login already.
     *
     * @param rootKey The share's root id.
     * @return True when it has.
     */
    fun hasShareLogin(rootKey: String): Boolean

    /**
     * Try a share's login on its server, and keep it once it works.
     *
     * @param root The share.
     * @param login The login.
     * @param isKept Whether it is kept across runs.
     * @return Ok once it works, or the refusal to word.
     */
    suspend fun giveShareLogin(root: ShareRoot, login: ShareLogin, isKept: Boolean): ChannelResult<Unit>

    /**
     * Forget a share's kept login.
     *
     * @param rootKey The share's root id.
     */
    fun forgetShareLogin(rootKey: String)

    /**
     * Show a share in the system's Files.
     *
     * @param rootKey The share's root id.
     */
    fun openShare(rootKey: String)

    /**
     * Press Connect on a shared desktop: its material is fetched and the viewer opens.
     *
     * @param bindingId The hub.
     * @param entryId The entry.
     * @param name What the viewer's bar shows.
     */
    fun connectDesktop(bindingId: String, entryId: String, name: String)

    /**
     * The codec and quality kept for a shared desktop, as its Configure dialog opens on them.
     *
     * @param bindingId The hub.
     * @param entryId The entry.
     * @return The choice.
     */
    fun remoteDesktopChoiceOf(bindingId: String, entryId: String): RemoteDesktopChoice

    /**
     * Save a shared desktop's Configure dialog; the next Connect asks for it.
     *
     * @param bindingId The hub.
     * @param entryId The entry.
     * @param choice The codec and quality.
     */
    fun configureRemoteDesktop(bindingId: String, entryId: String, choice: RemoteDesktopChoice)

    /** Close the remote desktop viewer. */
    fun closeDesktop()

    /**
     * Press Connect on a port entry: the phone's loopback forwards to it.
     *
     * @param bindingId The hub.
     * @param entryId The entry.
     * @param host The address the published port answers on.
     * @param port The published port number.
     */
    fun connectPort(bindingId: String, entryId: String, host: String, port: Int)

    /**
     * Press Disconnect on a forwarded port entry.
     *
     * @param bindingId The hub.
     * @param entryId The entry.
     */
    fun disconnectPort(bindingId: String, entryId: String)

    /**
     * One forwardable entry's local port, as the Configure dialog opens on it.
     *
     * @param bindingId The hub.
     * @param entryId The entry.
     * @return Automatic or fixed, with the number held.
     */
    fun localPortOf(bindingId: String, entryId: String): LocalPortChoice

    /**
     * Save the Configure dialog of a forwardable entry.
     *
     * @param bindingId The hub.
     * @param entryId The entry.
     * @param choice Automatic, or fixed with a number from 1024 to 65535.
     * @return Ok once kept, or the refusal the dialog words as `ui.reason.<code>`.
     */
    fun configurePort(bindingId: String, entryId: String, choice: LocalPortChoice): ChannelResult<Unit>

    /**
     * Press Open locally on a local-only web entry.
     *
     * @param bindingId The hub.
     * @param entryId The entry.
     * @param url The entry's address.
     */
    fun openLocal(bindingId: String, entryId: String, url: String)

    /**
     * Press Open on a web entry with `is_token_required`.
     *
     * @param bindingId The hub.
     * @param entryId The entry.
     * @param url The entry's address.
     */
    fun openWithToken(bindingId: String, entryId: String, url: String)
}
