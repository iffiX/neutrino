package io.github.iffix.neutrino.files

/**
 * How the system's Files opens a share's file, read from its mode string as
 * `ParcelFileDescriptor.parseMode` reads it: `r`, `w` and `wt` (emptied), `wa`, `rw`, `rwt`.
 *
 * @property isRead Whether the file is read.
 * @property isWrite Whether the file is written, and made when missing.
 * @property isTruncate Whether the file is emptied first.
 */
data class ShareOpenMode(val isRead: Boolean, val isWrite: Boolean, val isTruncate: Boolean) {
    companion object {
        /**
         * Read a mode string.
         *
         * @param mode The mode the system's Files asked for.
         * @return Its mode.
         * @throws IllegalArgumentException When the mode is none of the six.
         */
        fun parse(mode: String): ShareOpenMode = when (mode) {
            "r" -> ShareOpenMode(isRead = true, isWrite = false, isTruncate = false)
            "w", "wt" -> ShareOpenMode(isRead = false, isWrite = true, isTruncate = true)
            "wa" -> ShareOpenMode(isRead = false, isWrite = true, isTruncate = false)
            "rw" -> ShareOpenMode(isRead = true, isWrite = true, isTruncate = false)
            "rwt" -> ShareOpenMode(isRead = true, isWrite = true, isTruncate = true)
            else -> throw IllegalArgumentException("a file is not opened as $mode")
        }
    }
}
