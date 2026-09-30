package io.github.iffix.neutrino.files

/**
 * One file or folder of a share.
 *
 * @property name Its name.
 * @property isDirectory Whether it is a folder.
 * @property size Its size in bytes.
 * @property modifiedMillis When it last changed, in Unix milliseconds.
 */
data class ShareEntry(val name: String, val isDirectory: Boolean, val size: Long, val modifiedMillis: Long)
