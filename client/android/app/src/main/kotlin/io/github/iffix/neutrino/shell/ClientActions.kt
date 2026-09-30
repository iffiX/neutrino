package io.github.iffix.neutrino.shell

import io.github.iffix.neutrino.binding.HubBinding
import io.github.iffix.neutrino.channel.ChannelResult
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
}
