package io.github.iffix.neutrino.channel

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** What a call the hub, a link or the network can refuse returns: its value, or the `{code, params}`. */
sealed interface ChannelResult<out T> {
    /**
     * The call worked.
     *
     * @property value What it returned.
     */
    data class Ok<out T>(val value: T) : ChannelResult<T>

    /**
     * The call was refused, by the hub or on this side.
     *
     * @property code The refusal's code, worded by the catalog's `code.<code>`.
     * @property params The values a sentence about it needs.
     */
    data class Refused(val code: String, val params: JsonObject = JsonObject(emptyMap())) : ChannelResult<Nothing> {
        /** The parameters as the word catalog fills them in: strings, numbers and booleans as text. */
        val wordParams: Map<String, String>
            get() = params.mapValues { (_, value) -> textOf(value) }

        private fun textOf(value: JsonElement): String = when (value) {
            is JsonNull -> ""
            is JsonPrimitive -> value.content
            else -> value.toString()
        }
    }

    companion object {
        /**
         * A refusal with string parameters.
         *
         * @param code The code.
         * @param params The parameters.
         * @return The refusal.
         */
        fun refused(code: String, vararg params: Pair<String, String>): Refused =
            Refused(code, JsonObject(params.associate { (name, value) -> name to JsonPrimitive(value) }))
    }
}
