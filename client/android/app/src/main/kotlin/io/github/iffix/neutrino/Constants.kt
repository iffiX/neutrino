package io.github.iffix.neutrino

/** The languages every screen offers, as the desktop client names them. */
val CLIENT_LANGUAGES: List<String> = listOf("en", "zh-CN")

/** The language used when the phone's own is none of [CLIENT_LANGUAGES]. */
const val CLIENT_DEFAULT_LANGUAGE = "en"

/** The palettes the app draws itself in; `system` follows the phone. */
val CLIENT_THEMES: List<String> = listOf("system", "dark", "light")

/** The palette a fresh install draws in. */
const val CLIENT_DEFAULT_THEME = "system"

/** From this width, in dp, a window taller than it is wide shows the sidebar instead of the bottom bar. */
const val CLIENT_SIDEBAR_MIN_WIDTH_DP = 720

/** The height of the bottom bar, in dp, above the system's navigation bar. */
const val CLIENT_BOTTOM_BAR_HEIGHT_DP = 56

/** The file the language and the theme are kept in. */
const val CLIENT_SETTINGS_FILE_NAME = "client_settings"

/** The local port table's key in [CLIENT_SETTINGS_FILE_NAME]. */
const val CLIENT_SETTINGS_KEY_LOCAL_PORTS = "local_ports"

/** The remote desktops' codec and quality choices' key in [CLIENT_SETTINGS_FILE_NAME]. */
const val CLIENT_SETTINGS_KEY_RDP_CHOICES = "rdp_choices"

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

/** The app's licence, for the About card. */
const val CLIENT_LICENCE = "AGPL-3.0"

/** The edition released on GitHub, as `BuildConfig.EDITION` names it. */
const val EDITION_INTL = "intl"

/** The mainland edition, released on CNB. */
const val EDITION_CN = "cn"

/** The app's source, by edition: the repository each edition is released from. */
val CLIENT_SOURCE_URLS: Map<String, String> = mapOf(
    EDITION_INTL to "https://github.com/iffiX/neutrino",
    EDITION_CN to "https://cnb.cool/iffi-X/neutrino",
)

/** Where the app's source shows a file, by edition: `{blob}/<tag>/<path>` is the file at that tag. */
val CLIENT_BLOB_URLS: Map<String, String> = mapOf(
    EDITION_INTL to "https://github.com/iffiX/neutrino/blob",
    EDITION_CN to "https://cnb.cool/iffi-X/neutrino/-/blob",
)

/** The carried core whose source and patch the About card links. */
const val CLIENT_RUSTDESK_CORE = "RustDesk"

/** RustDesk's source at the tag the app's core is built from. */
const val CLIENT_RUSTDESK_SOURCE_URL = "https://github.com/rustdesk/rustdesk/tree/1.4.9"

/**
 * The patch the app's RustDesk core is built with, in the app's source at its release tag `v{version}`,
 * under the edition's `{blob}`.
 */
const val CLIENT_RUSTDESK_PATCH_URL = "{blob}/v{version}/packaging/build/build_core_rustdesk.patch"

/** The NetBird release the app's core is built from, as `build_core_netbird.py` pins it. */
const val OVERLAY_NETBIRD_VERSION = "0.78.1"

/**
 * The Go modules compiled into the transport library the app embeds, as `transport/go.mod` pins them, for
 * the About card.
 */
val CLIENT_TRANSPORT_MODULES: List<CarriedCore> = listOf(
    CarriedCore("flynn/noise", "1.1.0", "BSD-3-Clause", "https://github.com/flynn/noise/tree/v1.1.0"),
    CarriedCore("libp2p/go-buffer-pool", "0.0.2", "MIT", "https://github.com/libp2p/go-buffer-pool/tree/v0.0.2"),
    CarriedCore("libp2p/go-yamux", "4.0.2", "MPL-2.0", "https://github.com/libp2p/go-yamux/tree/v4.0.2"),
    CarriedCore("golang.org/x/crypto", "0.58.0", "BSD-3-Clause", "https://go.googlesource.com/crypto/+/v0.58.0"),
    CarriedCore("golang.org/x/sys", "0.49.0", "BSD-3-Clause", "https://go.googlesource.com/sys/+/v0.49.0"),
)

/**
 * The cores every edition of the app carries, for the About card. The mainland edition links EasyTier's
 * own Gitee repository and Gitee's RustDesk mirror, each holding the same tag at the same commit.
 */
val CLIENT_CARRIED_CORES: List<CarriedCore> = listOf(
    CarriedCore(
        "NetBird",
        OVERLAY_NETBIRD_VERSION,
        "BSD-3-Clause",
        "https://github.com/netbirdio/netbird/tree/v$OVERLAY_NETBIRD_VERSION",
    ),
    CarriedCore(
        "EasyTier",
        "2.6.4",
        "LGPL-3.0",
        "https://github.com/EasyTier/EasyTier/tree/v2.6.4",
        "{blob}/v{version}/packaging/build/build_core_easytier.patch",
        "https://gitee.com/easytier/EasyTier/tree/v2.6.4",
    ),
    CarriedCore(
        CLIENT_RUSTDESK_CORE,
        "1.4.9",
        "AGPL-3.0",
        CLIENT_RUSTDESK_SOURCE_URL,
        CLIENT_RUSTDESK_PATCH_URL,
        "https://gitee.com/mirrors/rustdesk/tree/1.4.9",
    ),
) + CLIENT_TRANSPORT_MODULES

/** The `platform_os` a desktop entry carries when the sharing machine is a Mac. */
const val CLIENT_PLATFORM_OS_DARWIN = "darwin"

/** The `platform_os` a desktop entry carries when the sharing machine runs Linux. */
const val CLIENT_PLATFORM_OS_LINUX = "linux"

/** The protocol number this build speaks; no prefix, one number has one name in every package. */
const val PROTOCOL = 4

/** The tag of every line the app writes to the system log. */
const val CLIENT_LOG_TAG = "neutrino"

/** The role this app joins a hub as. */
const val CLIENT_ROLE = "client"

/** The role a hub's welcome names. */
const val CLIENT_HUB_ROLE = "hub"

/** What `software` reads in the join body and the hello, before the version. */
const val CLIENT_SOFTWARE_PREFIX = "neutrino_client/"

/** What `os` reads in the platform this app reports. */
const val CLIENT_PLATFORM_OS = "android"

/** What a pasted or scanned link starts with. */
const val CLIENT_LINK_PREFIX = "neutrino://enroll/"

/** How many bytes one step of inflating a link's payload writes. */
const val CLIENT_LINK_INFLATE_CHUNK_BYTES = 1024

/** The one scheme of a hub's address this build dials; an address of any other scheme is skipped. */
const val CLIENT_ADDRESS_SCHEME = "tcp"

/** The bytes of a binding's static private key, kept as 64 lowercase hex characters. */
const val CLIENT_PRIVATE_KEY_BYTES = 32

/** The gomobile class the transport's library is bound to, in the one `.aar` it shares with NetBird. */
const val TRANSPORT_LIBRARY_CLASS = "io.netbird.gomobile.mobile.Mobile"

/** The bytes of the local channel's secret, made afresh at each start and written as hex. */
const val TRANSPORT_SECRET_BYTES = 32

/** How long a command to the transport waits for its answer. */
const val TRANSPORT_COMMAND_TIMEOUT_S = 5L

/** How long a `join` may take: a round's dial and handshake, then the hub's answer. */
const val TRANSPORT_JOIN_TIMEOUT_S = 30L

/** How long the app waits before it opens the transport's local channel again after it dropped. */
const val TRANSPORT_RECONNECT_MILLIS = 1000L

/** The record that accepts a stream. */
const val TRANSPORT_RECORD_ACCEPT = 2

/** A record of a stream's bytes. */
const val TRANSPORT_RECORD_DATA = 3

/** A terminal's new size, `{cols, rows}`. */
const val TRANSPORT_RECORD_RESIZE = 6

/** The record that ends a stream, `{code, params}`. */
const val TRANSPORT_RECORD_CLOSE = 8

/** The most one record's payload carries. */
const val TRANSPORT_RECORD_BYTES_MAX = 64 * 1024

/** The name every network a hub serves resolves to that hub's address on it. */
const val CLIENT_HUB_NAME = "hub.neutrino.internal"

/** How long telling a hub of a leave may take, after this phone has forgotten the binding. */
const val CLIENT_LEAVE_TELL_TIMEOUT_S = 5L

/** How long resolving the hub's name may take, and how long a phone with no network waits before it looks again. */
const val CLIENT_CONNECT_TIMEOUT_S = 10L

/** How often a report goes up while nothing changes. */
const val CLIENT_REPORT_INTERVAL_S = 30L

/** How often the live session sends this phone's `ping` frame, whose `pong` measures the round trip. */
const val CLIENT_PING_INTERVAL_S = 20L

/** The first wait after a broken wire, doubled on each failure. */
const val CLIENT_BACKOFF_MIN_S = 5L

/** The longest wait between two rounds, and the wait after a refusal the binding survives. */
const val CLIENT_BACKOFF_MAX_S = 60L

/** How long a refresh waits for a hub's state frame or a code before it ends. */
const val CLIENT_REFRESH_TIMEOUT_S = 10L

/** How long an armed destructive button waits for its second press. */
const val CLIENT_ARM_MILLIS = 5000L

/** How long a `service`, `persist` or `stop_session` frame waits for the hub's `reply`. */
const val CLIENT_STREAM_TIMEOUT_S = 15L

/** The refusal of a binding the hub does not hold: the row waits for Leave. */
const val CLIENT_REFUSAL_CODE_BINDING_UNKNOWN = "binding_unknown"

/** The refusal of a client older than the hub's floor: the row says to update the client. */
const val CLIENT_REFUSAL_CODE_PROTOCOL_TOO_OLD = "protocol_too_old"

/** The refusal of a session whose binding another client took. */
const val CLIENT_REFUSAL_CODE_REPLACED = "replaced"

/** The codes of a round, or a join, that no address answered: the next one runs at the backoff. */
val CLIENT_ROUND_SILENT_CODES: List<String> = listOf("hub_unreachable", "transport_missing", "transport_failed")

/** The hub's refusals a bound session or a join waits [CLIENT_BACKOFF_MAX_S] after and tries again. */
val CLIENT_ROUND_RETRIED_CODES: List<String> = listOf("control_unavailable", "channel_full")

/** The refusals the hub answers a protocol number it does not speak with. */
val CLIENT_PROTOCOL_REFUSAL_CODES: List<String> =
    listOf(CLIENT_REFUSAL_CODE_PROTOCOL_TOO_OLD, "protocol_too_new")

/** A shell on a managed machine. */
const val CLIENT_STREAM_KIND_SHELL = "shell"

/** The refusal of a join while the hub has paused new enrolments; the ticket stays good. */
const val CLIENT_REFUSAL_CODE_ADMISSION_PAUSED = "admission_paused"

/** The ways a client's session reaches its hub, each worded as `ui.through.<way>`. */
val CLIENT_REACHED_THROUGH: List<String> =
    listOf("lan", "netbird", "easytier", "ssh_relay", "direct", "sakurafrp", "openfrp")

/** The file the bindings are kept in, sealed under the Keystore's key. */
const val CLIENT_BINDINGS_FILE_NAME = "bindings.sealed"

/** The alias of the Keystore key every secret of the app is sealed under. */
const val CLIENT_KEYSTORE_ALIAS = "neutrino_client_secrets"

/** Every code the hub may send this app, each worded in both catalogs. */
val CLIENT_HUB_CODES: List<String> = listOf(
    "account_not_enabled",
    "account_unknown",
    "admission_paused",
    "agent_offline",
    "binding_unknown",
    "client_disabled",
    "connect_failed",
    "connect_limit",
    "control_unavailable",
    "hello_invalid",
    "hub_key_missing",
    "hub_unreachable",
    "hub_untrusted",
    "kind_unknown",
    "permission_denied",
    "port_not_published",
    "protocol_too_new",
    "protocol_too_old",
    "rdp_not_shared",
    "role_mismatch",
    "service_unknown",
    "session_not_owned",
    "session_unknown",
    "shell_program_unusable",
    "terminal_account_missing",
    "ticket_spent",
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

/** The hub's agent port, for an address that names none. */
const val CLIENT_AGENT_PORT_DEFAULT = 8443

/** The address every forward listens on. */
const val FORWARD_BIND_HOST = "127.0.0.1"

/** The query parameter a web page that needs a token takes it in. */
const val WEB_TOKEN_PARAMETER = "tkn"

/** The name under which a browser resolves every host to the loopback by itself. */
const val WEB_LOOPBACK_DOMAIN = "localhost"

/** The numbers a person may fix a local port to. */
val FORWARD_FIXED_PORTS: IntRange = 1024..65535

/** The numbers a forward of no app picks from, its pick kept for it: the panel's and a remote desktop's. */
val FORWARD_PICK_PORTS: IntRange = 20000..23999

/** How long after the hub closed a UDP forward's stream it is started again while its app is in use. */
const val FORWARD_UDP_RESTART_MILLIS = 1000L

/** A UDP `port` entry's protocol; every other entry is TCP. */
const val FORWARD_PROTOCOL_UDP = "udp"

/** The IPv4 wildcard address a free-port probe binds. */
const val FORWARD_PROBE_HOST_V4 = "0.0.0.0"

/** The IPv6 wildcard address a free-port probe binds where the phone has IPv6. */
const val FORWARD_PROBE_HOST_V6 = "::"

/** The entry part of the panel forward's key, `<binding>/#panel`; no published entry's id holds `#`. */
const val FORWARD_PANEL_ENTRY = "#panel"

/** The host label the panel opens under is this prefix and the hub's id. */
const val FORWARD_PANEL_SLUG_PREFIX = "panel-"

/** The notification channel the app core's foreground service posts in. */
const val CLIENT_CORE_NOTIFICATION_CHANNEL = "connections"

/** The id of the app core's notification. */
const val CLIENT_CORE_NOTIFICATION_ID = 7

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

/** How long a copy button shows that it copied. */
const val CLIENT_COPIED_SHOWN_MILLIS = 1500L

/** How long a connect's `login` stage may take: the engine's start, its login and its address. */
const val OVERLAY_LOGIN_TIMEOUT_S = 90L

/** The addresses a NetBird network gives its members, where the hub's own is looked for in its list. */
const val OVERLAY_NETBIRD_NETWORK = "100.64.0.0/10"

/** How long a disconnect waits for the engine to say it stopped. */
const val OVERLAY_STOP_TIMEOUT_S = 10L

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

/** The authority of the shares' documents provider. */
const val CLIENT_FILES_AUTHORITY = "io.github.iffix.neutrino.files"

/** The file the shares' kept logins are sealed in. */
const val CLIENT_SHARE_LOGINS_FILE_NAME = "shares.sealed"

/** How long one request to a share's server, a read or a write, may take. */
const val CLIENT_SHARE_IO_TIMEOUT_S = 60L

/** How long a share's held connection may sit unused before it is probed. */
const val CLIENT_SHARE_IDLE_PROBE_S = 30L

/** How long the probe of a share's held connection may take. */
const val CLIENT_SHARE_PROBE_TIMEOUT_S = 5L

/** How long a share stays listed in the system's Files after its hub's channel drops. */
const val CLIENT_SHARE_HOLD_S = 60L

/** How many names a new file or folder in a share tries, the taken name and its numbered ones. */
const val CLIENT_SHARE_NAME_ATTEMPTS = 32

/** The output a terminal tab keeps to draw again in a new view: the agent keeps as much. */
const val CLIENT_TERMINAL_KEPT_BYTES = 256 * 1024

/** How long a terminal tab's stream must be quiet before Clear stops dropping what arrives. */
const val CLIENT_TERMINAL_CLEAR_QUIET_MS = 500L

/** The longest a terminal tab drops what arrives after Clear. */
const val CLIENT_TERMINAL_CLEAR_MAX_MS = 20_000L

/** The least height, in dp, of the terminal's card, so a short window scrolls instead of squeezing the terminal. */
const val CLIENT_TERMINAL_CARD_MIN_HEIGHT_DP = 420

/** The least height, in dp, of the terminal's card while the keyboard is shown. */
const val CLIENT_TERMINAL_CARD_IME_MIN_HEIGHT_DP = 200

/** The page the terminals are drawn in. */
const val CLIENT_TERMINAL_PAGE = "file:///android_asset/terminal/index.html"

/** The escape character a terminal's key sequences start with. */
const val TERMINAL_ESCAPE = "\u001b"

/** The name the terminal page reaches the app by. */
const val CLIENT_TERMINAL_BRIDGE = "NeutrinoBridge"

/** The sixteen ANSI colours of every terminal in every theme, the Tango palette, by xterm.js's theme keys. */
val CLIENT_TERMINAL_ANSI_COLORS: Map<String, String> = linkedMapOf(
    "black" to "#2e3436",
    "red" to "#cc0000",
    "green" to "#4e9a06",
    "yellow" to "#c4a000",
    "blue" to "#3465a4",
    "magenta" to "#75507b",
    "cyan" to "#06989a",
    "white" to "#d3d7cf",
    "brightBlack" to "#555753",
    "brightRed" to "#ef2929",
    "brightGreen" to "#8ae234",
    "brightYellow" to "#fce94f",
    "brightBlue" to "#729fcf",
    "brightMagenta" to "#ad7fa8",
    "brightCyan" to "#34e2e2",
    "brightWhite" to "#eeeeec",
)

/** The analysis frame the QR scanner asks the camera for. */
const val SCAN_ANALYSIS_WIDTH = 1920

/** The analysis frame's height. */
const val SCAN_ANALYSIS_HEIGHT = 1080

/** The side of the centred square decoded, and drawn as the guide, over the frame's shorter side. */
const val SCAN_REGION_FRACTION = 0.7f

/** The vibration of a decoded code where the phone has no confirm haptic. */
const val SCAN_VIBRATION_MILLIS = 50L

/** The machines whose RustDesk core is built with `mediacodec`, so it decodes H264 and H265 in hardware too. */
val RDP_MEDIACODEC_ABIS: List<String> = listOf("arm64-v8a")

/** RustDesk's peer option naming the codec a session asks for. */
const val RDP_OPTION_CODEC = "codec-preference"

/** The core's session option naming the picture quality, kept in the peer's `image_quality`. */
const val RDP_OPTION_QUALITY = "image-quality"

/** RustDesk's mouse event type in the low three bits of a mask: the pointer moved. */
const val RDP_MOUSE_MOVE = 0

/** RustDesk's mouse event type: a button pressed. */
const val RDP_MOUSE_DOWN = 1

/** RustDesk's mouse event type: a button released. */
const val RDP_MOUSE_UP = 2

/** RustDesk's mouse event type: the wheel turned; the event's y carries the steps. */
const val RDP_MOUSE_WHEEL = 3

/** The left button, above the type bits of a mask. */
const val RDP_MOUSE_LEFT = 1 shl 3

/** The right button, above the type bits of a mask. */
const val RDP_MOUSE_RIGHT = 2 shl 3

/** The finger travel, in pixels, of one wheel step in a two-finger scroll. */
const val RDP_SCROLL_STEP_PX = 24f

/** The change in finger spread, in pixels, that makes a two-finger gesture a pinch. */
const val RDP_PINCH_SLOP_PX = 24f

/** The largest zoom a pinch reaches, over the picture fitted to the viewer. */
const val RDP_ZOOM_MAX = 6f

/** The RustDesk core's state: logged in, frames follow. */
const val RDP_STATE_CONNECTED = 1

/** The RustDesk core's state: the machine refused the password. */
const val RDP_STATE_LOGIN_FAILED = 2

/** The RustDesk core's state: the connection ended. */
const val RDP_STATE_CLOSED = 3

/** The pause between two typed characters, so a Linux desktop types one before the next arrives. */
const val RDP_TYPE_PACE_MILLIS = 40L

/** The last character of ASCII; text with any character above it goes to a Linux host as a paste. */
const val RDP_ASCII_LAST = 0x7F
