package io.github.iffix.neutrino.shell

import android.content.Intent
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.files.ShareLogin
import io.github.iffix.neutrino.files.ShareRoot
import io.github.iffix.neutrino.forward.LocalPortChoice
import io.github.iffix.neutrino.remotedesktop.RemoteDesktopChoice

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

    /** Refresh every hub, and drop every error line. */
    fun refresh()

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
     */
    fun copy(text: String)

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
     * Press Connect on a shared desktop: its seat password is read, its forward is made, and the
     * viewer opens on the forward.
     *
     * @param bindingId The hub.
     * @param entryId The entry.
     * @param name What the viewer's bar shows.
     * @param platformOs The `platform_os` the entry carries, or empty when it names none.
     * @param port The entry's own port, which its forward tries first on the loopback.
     */
    fun connectDesktop(bindingId: String, entryId: String, name: String, platformOs: String, port: Int)

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
     * Press Disconnect on a forwarded web entry.
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
     * Press Open on a web entry: its forward, its token when it needs one, then the browser.
     *
     * @param bindingId The hub.
     * @param entryId The entry.
     * @param url The entry's address.
     * @param isTokenRequired Whether the page opens with a token.
     */
    fun openWeb(bindingId: String, entryId: String, url: String, isTokenRequired: Boolean)

    /**
     * Press Panel on a hub's row: the panel's forward, then the browser.
     *
     * @param bindingId The hub.
     */
    fun openPanel(bindingId: String)
}
