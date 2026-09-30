package io.github.iffix.neutrino.shell

import android.content.Intent
import io.github.iffix.neutrino.binding.HubBinding
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.files.ShareLogin
import io.github.iffix.neutrino.files.ShareRoot
import kotlinx.serialization.json.JsonObject

/** What a person can do from a screen; the screens call these and draw what comes back. */
interface ClientActions {
    /**
     * Join the hub a pasted or scanned link names.
     *
     * @param link The link's text.
     * @return The binding kept, or the refusal to word.
     */
    suspend fun join(link: String): ChannelResult<HubBinding>

    /**
     * Leave one hub.
     *
     * @param bindingId The binding's id.
     * @return Ok once forgotten, or the refusal that kept it.
     */
    suspend fun leave(bindingId: String): ChannelResult<Unit>

    /**
     * The material one published entry takes from its hub.
     *
     * @param bindingId The hub's binding.
     * @param entryId The entry's id.
     * @return The material, or the refusal to word.
     */
    suspend fun serviceMaterial(bindingId: String, entryId: String): ChannelResult<JsonObject>

    /**
     * Take a hub's binding back from a socket that replaced this one.
     *
     * @param bindingId The binding's id.
     */
    fun reconnect(bindingId: String)

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
     * Want, or stop wanting, one hub's virtual network.
     *
     * @param bindingId The hub.
     * @param isWanted The wish.
     */
    fun setOverlayWanted(bindingId: String, isWanted: Boolean)

    /**
     * Pick which of a hub's virtual networks to join.
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
     * Show a share in the system's Files.
     *
     * @param rootKey The share's root id.
     */
    fun openShare(rootKey: String)
}
