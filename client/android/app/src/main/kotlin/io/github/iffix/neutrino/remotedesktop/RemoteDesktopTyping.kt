package io.github.iffix.neutrino.remotedesktop

/**
 * One change of the viewer's hidden text field, as the keys that make it on the remote machine:
 * Backspaces for what was taken away from the end, then the text added.
 *
 * @property backspaces How many characters to delete.
 * @property text What to type after them.
 */
data class RemoteDesktopTyping(val backspaces: Int, val text: String) {
    companion object {
        /**
         * The keys that turn one content of the field into the next. A keyboard that composes a
         * word replaces the whole word on each letter; only the difference is sent.
         *
         * @param before What the field held.
         * @param after What it holds now.
         * @return The Backspaces and the text.
         */
        fun between(before: String, after: String): RemoteDesktopTyping {
            val kept = before.commonPrefixWith(after).length
            return RemoteDesktopTyping(before.length - kept, after.substring(kept))
        }
    }
}
