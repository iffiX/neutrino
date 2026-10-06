package io.github.iffix.neutrino.files

import java.nio.file.FileAlreadyExistsException

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

    /**
     * Make this document under the first name not taken, as the system's own Files names a copy:
     * the name itself, then ` (1)`, ` (2)` and on before a file's extension, at a folder's end.
     *
     * @param isDirectory Whether the document is a folder.
     * @param attempts How many names are tried.
     * @param make Makes one name only when it is free; false when the name is taken.
     * @return The document made.
     * @throws FileAlreadyExistsException When every name tried is taken.
     */
    fun makeFree(isDirectory: Boolean, attempts: Int, make: (ShareDocumentId) -> Boolean): ShareDocumentId {
        val dot = name.lastIndexOf('.')
        val stem = if (isDirectory || dot <= 0) name else name.substring(0, dot)
        val extension = name.removePrefix(stem)
        val parent = path.removeSuffix(name)
        for (number in 0 until attempts) {
            val document = ShareDocumentId(rootKey, parent + if (number == 0) name else "$stem ($number)$extension")
            if (make(document)) return document
        }
        throw FileAlreadyExistsException(path, null, "the first $attempts names are taken")
    }

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
