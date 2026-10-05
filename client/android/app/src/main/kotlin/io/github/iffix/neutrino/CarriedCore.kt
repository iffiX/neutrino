package io.github.iffix.neutrino

/**
 * One core built into the app, as the About card lists it.
 *
 * @property name The core's name.
 * @property version The version it is built from.
 * @property licence Its licence.
 * @property sourceUrl Its source at that version.
 * @property patchUrl The patch it is built with, under the app's source `{source}` at its release tag
 *   `v{version}`; empty for none.
 * @property mainlandSourceUrl The same source at the same version on a mirror a mainland reader can open,
 *   which the mainland edition links instead; empty for none.
 */
data class CarriedCore(
    val name: String,
    val version: String,
    val licence: String,
    val sourceUrl: String,
    val patchUrl: String = "",
    val mainlandSourceUrl: String = "",
)
