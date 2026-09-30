package io.github.iffix.neutrino

/** The languages every screen offers, as the desktop client names them. */
val CLIENT_LANGUAGES: List<String> = listOf("en", "zh-CN")

/** The language used when the phone's own is none of [CLIENT_LANGUAGES]. */
const val CLIENT_DEFAULT_LANGUAGE = "en"

/** The palettes the app draws itself in; `system` follows the phone. */
val CLIENT_THEMES: List<String> = listOf("system", "dark", "light")

/** The palette a fresh install draws in. */
const val CLIENT_DEFAULT_THEME = "system"

/** Past this width, in dp, a landscape window shows the sidebar instead of the bottom bar. */
const val CLIENT_SIDEBAR_MIN_WIDTH_DP = 880

/** The file the language and the theme are kept in. */
const val CLIENT_SETTINGS_FILE_NAME = "client_settings"

/** The language's key in [CLIENT_SETTINGS_FILE_NAME]. */
const val CLIENT_SETTINGS_KEY_LANGUAGE = "language"

/** The theme's key in [CLIENT_SETTINGS_FILE_NAME]. */
const val CLIENT_SETTINGS_KEY_THEME = "theme"

/** Where the desktop client's word catalogs land inside the app's assets. */
const val CLIENT_DESKTOP_LOCALES_DIR = "locales/desktop"

/** Where the app's own word catalogs live inside its assets. */
const val CLIENT_APP_LOCALES_DIR = "locales/app"

/** The edge of the box every icon's path data is drawn in. */
const val ICON_VIEWBOX = 24f

/** The width of an icon's stroke, in units of [ICON_VIEWBOX]. */
const val ICON_STROKE_WIDTH = 1.6f

/** The cores the app carries, as name, version and licence, for the About screen. */
val CLIENT_CARRIED_CORES: List<Triple<String, String, String>> = listOf(
    Triple("NetBird", "0.78.1", "BSD-3-Clause"),
    Triple("EasyTier", "2.6.4", "LGPL-3.0"),
    Triple("RustDesk", "1.4.9", "AGPL-3.0"),
)

/** The protocol number this build speaks; no prefix, one number has one name in every package. */
const val PROTOCOL = 3

/** The role this app joins a hub as. */
const val CLIENT_ROLE = "client"

/** The role a hub's welcome names. */
const val CLIENT_HUB_ROLE = "hub"

/** What `software` reads in the join body and the hello, before the version. */
const val CLIENT_SOFTWARE_PREFIX = "neutrino_client/"

/** What `os` reads in the platform this app reports. */
const val CLIENT_PLATFORM_OS = "android"

/** What a pasted link starts with. */
const val CLIENT_LINK_PREFIX = "neutrino://enroll/"

/** The path a binding starts at, on the pinned agent port. */
const val CLIENT_JOIN_PATH = "/api/channel/join"

/** The path a binding ends at. */
const val CLIENT_LEAVE_PATH = "/api/channel/leave"

/** The path of the one socket. */
const val CLIENT_CHANNEL_WS_PATH = "/api/channel/socket"

/** The name every network a hub serves resolves to that hub's address on it. */
const val CLIENT_HUB_NAME = "hub.neutrino.internal"

/** How long a join or a leave may take. */
const val CLIENT_REQUEST_TIMEOUT_S = 10L

/** How long connecting and the handshake on top of it may take together. */
const val CLIENT_CONNECT_TIMEOUT_S = 10L

/** How often a report goes up while nothing changes. */
const val CLIENT_REPORT_INTERVAL_S = 30L

/** How long the open socket may stay silent before it counts as dead. */
const val CLIENT_WS_SILENCE_TIMEOUT_S = 45L

/** The first wait after a broken wire, doubled on each failure. */
const val CLIENT_BACKOFF_MIN_S = 5L

/** The longest wait between two rounds, and the wait after a refusal the binding survives. */
const val CLIENT_BACKOFF_MAX_S = 60L

/** The pause between an address that did not answer and the next of the round. */
const val CLIENT_ROTATE_DELAY_S = 1L

/** How often an idle session looks again: one another socket replaced, or the hub forgot. */
const val CLIENT_IDLE_POLL_INTERVAL_S = 2L

/** How long a stream this side opened waits for the hub's close. */
const val CLIENT_STREAM_TIMEOUT_S = 15L

/** A byte stream's credit window; half of it consumed sends the next grant. */
const val CLIENT_STREAM_CREDIT_BYTES = 1024 * 1024

/** The most one binary frame carries. */
const val CLIENT_WS_CHUNK_BYTES = 64 * 1024

/** How long a send waits for the hub's credit. */
const val CLIENT_WS_CREDIT_TIMEOUT_S = 60L

/** The close code after a `refused` frame. */
const val CLIENT_WS_CLOSE_REFUSED = 4000

/** The close code of a socket another socket for the same binding replaced. */
const val CLIENT_WS_CLOSE_REPLACED = 4010

/** The code this side closes a stream the hub opened with: a client serves no kind. */
const val CLIENT_STREAM_CODE_KIND_UNKNOWN = "kind_unknown"

/** The one refusal that unbinds: the hub holds no such binding. */
const val CLIENT_REFUSAL_CODE_BINDING_UNKNOWN = "binding_unknown"

/** The refusals the hub answers a protocol number it does not speak with. */
val CLIENT_PROTOCOL_REFUSAL_CODES: List<String> = listOf("protocol_too_old", "protocol_too_new")

/** A stream for one published entry's material. */
const val CLIENT_STREAM_KIND_SERVICE = "service"

/** A shell on a managed machine. */
const val CLIENT_STREAM_KIND_SHELL = "shell"

/** A command on a managed machine, such as a shell's resize. */
const val CLIENT_STREAM_KIND_COMMAND = "command"

/** The file the bindings are kept in, sealed under the Keystore's key. */
const val CLIENT_BINDINGS_FILE_NAME = "bindings.sealed"

/** The alias of the Keystore key every secret of the app is sealed under. */
const val CLIENT_KEYSTORE_ALIAS = "neutrino_client_secrets"

/** Every code the hub may send this app, each worded in both catalogs. */
val CLIENT_HUB_CODES: List<String> = listOf(
    "agent_offline",
    "binding_unknown",
    "client_disabled",
    "hello_invalid",
    "kind_unknown",
    "permission_denied",
    "protocol_too_new",
    "protocol_too_old",
    "rdp_not_shared",
    "role_mismatch",
    "service_unknown",
    "shell_unknown",
    "vault_locked",
    "verb_unknown",
)

/** NetBird's provider name in an overlay object. */
const val OVERLAY_PROVIDER_NETBIRD = "netbird"

/** EasyTier's provider name in an overlay object. */
const val OVERLAY_PROVIDER_EASYTIER = "easytier"

/** EasyTier with the network named in the overlay object. */
const val OVERLAY_EASYTIER_MODE_MANUAL = "manual"

/** EasyTier with the network pushed by a console. */
const val OVERLAY_EASYTIER_MODE_CONSOLE = "console"

/** A socket closed from this side with nothing to say. */
const val CLIENT_WS_CLOSE_NORMAL = 1000

/** The port of an `https` address that names none. */
const val CLIENT_HTTPS_DEFAULT_PORT = 443

/** The first id this side opens a stream at; the hub's are even. */
const val CHANNEL_FIRST_STREAM_ID = 1

/** The step between two ids one side opens. */
const val CHANNEL_STREAM_ID_STEP = 2

/** The big-endian stream id at the head of a binary frame. */
const val CHANNEL_STREAM_ID_BYTES = 4

/** The Keystore the sealing key lives in. */
const val SEAL_KEYSTORE = "AndroidKeyStore"

/** How a secret is sealed. */
const val SEAL_TRANSFORMATION = "AES/GCM/NoPadding"

/** The nonce at the head of a sealed value. */
const val SEAL_NONCE_BYTES = 12

/** The GCM tag's length. */
const val SEAL_TAG_BITS = 128

/** The sealing key's length. */
const val SEAL_KEY_BITS = 256

/** The clip extra that keeps a copied secret out of the clipboard's preview, read from Android 13. */
const val CLIENT_CLIP_SENSITIVE_EXTRA = "android.content.extra.IS_SENSITIVE"

/** How long a copy button shows that it copied. */
const val CLIENT_COPIED_SHOWN_MILLIS = 1500L

/** How many characters of a masked key stay readable. */
const val CLIENT_KEY_SHOWN_PREFIX = 6

/** How long a hub's channel may be lost before the phone moves to the hub's next network. */
const val CLIENT_OVERLAY_FAILOVER_S = 30L

/** How often the overlay controller looks at the channels again while nothing changes. */
const val OVERLAY_CHECK_INTERVAL_S = 5L

/** The name of the one manual EasyTier instance the app runs. */
const val OVERLAY_EASYTIER_INSTANCE = "neutrino"

/** How often an EasyTier engine reads its core's state. */
const val OVERLAY_POLL_MILLIS = 1000L

/** The MTU of an EasyTier TUN device. */
const val OVERLAY_TUN_MTU = 1380

/** NetBird's own management plane, for a hub that names none. */
const val OVERLAY_NETBIRD_DEFAULT_MANAGEMENT_URL = "https://api.netbird.io:443"

/** The VPN service's action that runs one hub's network. */
const val OVERLAY_SERVICE_ACTION_START = "io.github.iffix.neutrino.overlay.START"

/** The VPN service's action that leaves the network. */
const val OVERLAY_SERVICE_ACTION_STOP = "io.github.iffix.neutrino.overlay.STOP"

/** The extra naming the hub's binding. */
const val OVERLAY_SERVICE_EXTRA_BINDING = "binding_id"

/** The extra naming the network's provider. */
const val OVERLAY_SERVICE_EXTRA_PROVIDER = "provider"
