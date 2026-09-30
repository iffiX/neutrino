package io.github.iffix.neutrino.channel

import io.github.iffix.neutrino.CLIENT_PLATFORM_OS
import io.github.iffix.neutrino.CLIENT_SOFTWARE_PREFIX

/**
 * What this phone says about itself in a join and every report.
 *
 * @property machineId This installation's id.
 * @property hostname The name the phone goes by.
 * @property arch The architecture, `arm64` or `amd64`.
 * @property osVersion The Android release, such as `15`.
 * @property version The app's version.
 */
data class ClientMachine(
    val machineId: String,
    val hostname: String,
    val arch: String,
    val osVersion: String,
    val version: String,
) {
    /** `neutrino_client/<version>`. */
    val software: String
        get() = CLIENT_SOFTWARE_PREFIX + version

    /** The platform tuple: `{os, family, arch, version}`, family empty off Linux. */
    val platform: Map<String, String>
        get() = linkedMapOf("os" to CLIENT_PLATFORM_OS, "family" to "", "arch" to arch, "version" to osVersion)
}
