package io.github.iffix.neutrino.files

import java.io.Closeable

/** One file of a share opened over its own connection. */
interface ShareFileLink : Closeable {
    /** The file's size in bytes when it was opened. */
    val size: Long

    /**
     * Read from the file.
     *
     * @param offset Where in the file.
     * @param data Where the bytes go, from its start.
     * @param count How many bytes at most.
     * @return How many bytes were read; -1 at the end.
     */
    fun read(offset: Long, data: ByteArray, count: Int): Int

    /**
     * Write to the file.
     *
     * @param offset Where in the file.
     * @param data The bytes, from its start.
     * @param count How many.
     */
    fun write(offset: Long, data: ByteArray, count: Int)
}
