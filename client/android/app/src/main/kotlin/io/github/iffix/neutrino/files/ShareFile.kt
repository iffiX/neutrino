package io.github.iffix.neutrino.files

import java.io.Closeable

/**
 * A file the system's Files reads or writes through the provider, by offset: a read or a write
 * that fails opens the file again on a new connection and tries once more.
 *
 * @param open Open the file; true opens it again after a failure, which never empties it.
 */
class ShareFile(private val open: (Boolean) -> ShareFileLink) : Closeable {
    private var link: ShareFileLink = open(false)

    /** The file's size in bytes when it was first opened. */
    val size: Long = link.size

    /**
     * Read from the file.
     *
     * @param offset Where in the file.
     * @param data Where the bytes go, from its start.
     * @param count How many bytes at most.
     * @return How many bytes were read; -1 at the end.
     * @throws Exception What the second attempt threw.
     */
    @Synchronized
    fun read(offset: Long, data: ByteArray, count: Int): Int = retried { it.read(offset, data, count) }

    /**
     * Write to the file.
     *
     * @param offset Where in the file.
     * @param data The bytes, from its start.
     * @param count How many.
     * @throws Exception What the second attempt threw.
     */
    @Synchronized
    fun write(offset: Long, data: ByteArray, count: Int) = retried { it.write(offset, data, count) }

    @Synchronized
    override fun close() = closeQuietly(link)

    private fun <T> retried(action: (ShareFileLink) -> T): T = try {
        action(link)
    } catch (_: Exception) {
        closeQuietly(link)
        link = open(true)
        action(link)
    }

    private fun closeQuietly(gone: ShareFileLink) {
        try {
            gone.close()
        } catch (_: Exception) {
            // The connection was already gone.
        }
    }
}
