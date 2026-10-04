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

/** The app's source. */
const val CLIENT_SOURCE_URL = "https://github.com/iffiX/neutrino"

/** The carried core whose source and patch the About card links. */
const val CLIENT_RUSTDESK_CORE = "RustDesk"

/** RustDesk's source at the tag the app's core is built from. */
const val CLIENT_RUSTDESK_SOURCE_URL = "https://github.com/rustdesk/rustdesk/tree/1.4.9"

/** The patch the app's RustDesk core is built with, at the app's release tag `v{version}`. */
const val CLIENT_RUSTDESK_PATCH_URL =
    "https://github.com/iffiX/neutrino/blob/v{version}/packaging/build/build_core_rustdesk.patch"

/** The cores the app carries, for the About card. */
val CLIENT_CARRIED_CORES: List<CarriedCore> = listOf(
    CarriedCore("NetBird", "0.78.1", "BSD-3-Clause", "https://github.com/netbirdio/netbird/tree/v0.78.1"),
    CarriedCore(
        "EasyTier",
        "2.6.4",
        "LGPL-3.0",
        "https://github.com/EasyTier/EasyTier/tree/v2.6.4",
        "https://github.com/iffiX/neutrino/blob/v{version}/packaging/build/build_core_easytier.patch",
    ),
    CarriedCore(CLIENT_RUSTDESK_CORE, "1.4.9", "AGPL-3.0", CLIENT_RUSTDESK_SOURCE_URL, CLIENT_RUSTDESK_PATCH_URL),
)

/** The `platform_os` a desktop entry carries when the sharing machine is a Mac. */
const val CLIENT_PLATFORM_OS_DARWIN = "darwin"

/** The `platform_os` a desktop entry carries when the sharing machine runs Linux. */
const val CLIENT_PLATFORM_OS_LINUX = "linux"

/** The protocol number this build speaks; no prefix, one number has one name in every package. */
const val PROTOCOL = 3

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

/** The path a binding starts at, on the pinned agent port. */
const val CLIENT_JOIN_PATH = "/api/channel/join"

/** The path a binding ends at. */
const val CLIENT_LEAVE_PATH = "/api/channel/leave"

/** The path of the one socket. */
const val CLIENT_CHANNEL_WS_PATH = "/api/channel/socket"

/** The name every network a hub serves resolves to that hub's address on it. */
const val CLIENT_HUB_NAME = "hub.neutrino.internal"

/** How long a join or a request to the hub may take. */
const val CLIENT_REQUEST_TIMEOUT_S = 10L

/** How long telling a hub of a leave may take, after this phone has forgotten the binding. */
const val CLIENT_LEAVE_TELL_TIMEOUT_S = 5L

/** How long connecting and the handshake on top of it may take together. */
const val CLIENT_CONNECT_TIMEOUT_S = 10L

/** How often a report goes up while nothing changes. */
const val CLIENT_REPORT_INTERVAL_S = 30L

/** How long the open socket may stay silent before it counts as dead. */
const val CLIENT_WS_SILENCE_TIMEOUT_S = 45L

/** How often the open socket sends a WebSocket ping, so a socket the network dropped closes. */
const val CLIENT_WS_PING_INTERVAL_S = 20L

/** The first wait after a broken wire, doubled on each failure. */
const val CLIENT_BACKOFF_MIN_S = 5L

/** The longest wait between two rounds, and the wait after a refusal the binding survives. */
const val CLIENT_BACKOFF_MAX_S = 60L

/** The pause between an address that did not answer and the next of the round. */
const val CLIENT_ROTATE_DELAY_S = 1L

/** How long a refresh waits for a hub's state frame or a code before it ends. */
const val CLIENT_REFRESH_TIMEOUT_S = 10L

/** How long the notice of a hub that no longer knows this phone stays on the Hubs page. */
const val CLIENT_NOTICE_SHOWN_S = 60L

/** How long an armed destructive button waits for its second press. */
const val CLIENT_ARM_MILLIS = 5000L

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

/** The codes a person has to act on, drawn with a red dot. */
val CLIENT_PERSON_CODES: List<String> =
    listOf("hub_untrusted", "binding_unknown", "protocol_too_old", "protocol_too_new")

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
    "session_not_owned",
    "session_unknown",
    "shell_unknown",
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

/** A socket closed from this side with nothing to say. */
const val CLIENT_WS_CLOSE_NORMAL = 1000

/** The port of an `https` address that names none. */
const val CLIENT_HTTPS_DEFAULT_PORT = 443

/** The port of an `http` address that names none. */
const val CLIENT_HTTP_DEFAULT_PORT = 80

/** The address every forward listens on. */
const val FORWARD_BIND_HOST = "127.0.0.1"

/** The most one read of a forwarded connection copies at once. */
const val FORWARD_BUFFER_BYTES = 65536

/** How long a forwarded connection may take to reach the published port, as the desktop's relay allows. */
const val FORWARD_CONNECT_TIMEOUT_MILLIS = 10_000

/** The query parameter a local-only web page takes its token in. */
const val WEB_TOKEN_PARAMETER = "tkn"

/** The name under which a browser resolves every host to the loopback by itself. */
const val WEB_LOOPBACK_DOMAIN = "localhost"

/** The numbers a person may fix a local port to. */
val FORWARD_FIXED_PORTS: IntRange = 1024..65535

/** Where an automatic local port is looked for when the entry's own is taken. */
const val FORWARD_AUTO_FIRST_PORT = 20000

/** The notification channel the app core's foreground service posts in. */
const val CLIENT_CORE_NOTIFICATION_CHANNEL = "connections"

/** The id of the app core's notification. */
const val CLIENT_CORE_NOTIFICATION_ID = 7

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

/** How long a connect's `login` stage may take: the engine's start, its login and its address. */
const val OVERLAY_LOGIN_TIMEOUT_S = 90L

/** The addresses a NetBird network gives its members, where the hub's own is looked for in its list. */
const val OVERLAY_NETBIRD_NETWORK = "100.64.0.0/10"

/** How long a disconnect waits for the engine to say it stopped. */
const val OVERLAY_STOP_TIMEOUT_S = 10L

/** The name of the one manual EasyTier instance the app runs. */
const val OVERLAY_EASYTIER_INSTANCE = "neutrino"

/** How often a connect asks whether the hub answers at its address on the network. */
const val OVERLAY_PROBE_INTERVAL_MILLIS = 2000L

/** How long one such ask waits for the hub's port. */
const val OVERLAY_PROBE_TIMEOUT_MILLIS = 3000

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

/** How long reaching a share's server may take. */
const val CLIENT_SHARE_CONNECT_TIMEOUT_S = 5L

/** How long one request to a share's server, a read or a write, may take. */
const val CLIENT_SHARE_IO_TIMEOUT_S = 60L

/** How long a share's held connection may sit unused before it is probed. */
const val CLIENT_SHARE_IDLE_PROBE_S = 30L

/** How long the probe of a share's held connection may take. */
const val CLIENT_SHARE_PROBE_TIMEOUT_S = 5L

/** How long a share stays listed in the system's Files after its hub's channel drops. */
const val CLIENT_SHARE_HOLD_S = 60L

/** The output a terminal tab keeps to draw again in a new view: the agent keeps as much. */
const val CLIENT_TERMINAL_KEPT_BYTES = 256 * 1024

/** How long, after Clear, a terminal tab drops the output that arrives. */
const val CLIENT_TERMINAL_CLEAR_DROP_MS = 1000L

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
