package io.github.iffix.neutrino.files

import kotlinx.serialization.Serializable

/**
 * The account one share is opened with.
 *
 * @property user The account's name.
 * @property password Its password.
 */
@Serializable
data class ShareLogin(val user: String, val password: String)
