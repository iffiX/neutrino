package io.github.iffix.neutrino.netbird

/** NetBird's provider name in an overlay object. */
const val OVERLAY_PROVIDER_NETBIRD = "netbird"

/** The addresses a NetBird network gives its members, where the hub's own is looked for in its list. */
const val OVERLAY_NETBIRD_NETWORK = "100.64.0.0/10"

/** NetBird's own management plane, for a hub that names none. */
const val OVERLAY_NETBIRD_DEFAULT_MANAGEMENT_URL = "https://api.netbird.io:443"

/** The NetBird release the app's core is built from, as `build_core_netbird.py` pins it. */
const val OVERLAY_NETBIRD_VERSION = "0.78.1"

/** NetBird's source at that release. */
const val OVERLAY_NETBIRD_SOURCE_URL = "https://github.com/netbirdio/netbird/tree/v$OVERLAY_NETBIRD_VERSION"
