package io.github.iffix.neutrino.files

/**
 * A document of a share, as the system's Files names it: the root's id, then the path inside the
 * share with `/` between its parts, empty for the share itself.
 *
 * @property rootKey The share's root id.
 * @property path The path inside the share.
 */
data class ShareDocumentId(val rootKey: String, val path: String) {
    /** The id the system's Files keeps: `<root>/<path>`. */
    val encoded: String
        get() = "$rootKey/$path"

    /** The path as SMB spells it, with `\` between the parts. */
    val smbPath: String
        get() = path.replace('/', '\\')

    /** The last part of the path, empty for the share itself. */
    val name: String
        get() = path.substringAfterLast('/')

    /**
     * A document inside this one.
     *
     * @param child The child's name.
     * @return Its id.
     */
    fun child(child: String): ShareDocumentId = ShareDocumentId(rootKey, if (path.isEmpty()) child else "$path/$child")

    companion object {
        /**
         * Read an id the system's Files handed back.
         *
         * @param encoded The id.
         * @return The document.
         * @throws IllegalArgumentException When the id names no root.
         */
        fun decode(encoded: String): ShareDocumentId {
            val slash = encoded.indexOf('/')
            require(slash > 0) { "a document id starts with its root" }
            return ShareDocumentId(encoded.substring(0, slash), encoded.substring(slash + 1).trim('/'))
        }
    }
}
