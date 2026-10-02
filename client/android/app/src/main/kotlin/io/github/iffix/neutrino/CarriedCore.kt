package io.github.iffix.neutrino

/**
 * One core built into the app, as the About card lists it.
 *
 * @property name The core's name.
 * @property version The version it is built from.
 * @property licence Its licence.
 * @property sourceUrl Its source at that version.
 * @property patchUrl The patch it is built with, at the app's release tag `v{version}`; empty for none.
 */
data class CarriedCore(
    val name: String,
    val version: String,
    val licence: String,
    val sourceUrl: String,
    val patchUrl: String = "",
)
