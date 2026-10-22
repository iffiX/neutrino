import Foundation

/// What the app names about itself: its role, its languages, its themes, its layout and its source.
enum Client {
    /// The role this app joins a hub as.
    static let role = "client"

    /// The role a hub's welcome names.
    static let hubRole = "hub"

    /// What `software` reads in the join body and the hello, before the version.
    static let softwarePrefix = "neutrino_client/"

    /// What `os` reads in the platform this app reports.
    static let platformOs = "ios"

    /// The languages every page offers, as the desktop client names them.
    static let languages = ["en", "zh-CN"]

    /// The language used when the phone's own is none of `languages`.
    static let defaultLanguage = "en"

    /// The palettes the app draws itself in; `system` follows the phone.
    static let themes = ["system", "dark", "light"]

    /// The palette a fresh install draws in.
    static let defaultTheme = "system"

    /// From this width, in points, a window taller than it is wide shows the sidebar instead of the bottom bar.
    static let sidebarMinWidth: Double = 720

    /// The sidebar's width, in points.
    static let sidebarWidth: Double = 200

    /// The height of the page header, and of the sidebar's name box beside it, in points.
    static let headerHeight: Double = 48

    /// The height of the bottom bar, above the screen's safe area at its foot, in points.
    static let barHeight: Double = 56

    /// The app's licence, for the About card.
    static let licence = "AGPL-3.0"

    /// The edition released on GitHub, as `NeutrinoEdition` names it.
    static let editionIntl = "intl"

    /// The mainland edition.
    static let editionCn = "cn"

    /// The Info.plist key the build writes the edition under.
    static let editionInfoKey = "NeutrinoEdition"

    /// The app's source, by edition.
    static let sourceUrls = [
        editionIntl: "https://github.com/iffiX/neutrino",
        editionCn: "https://gitee.com/iffiX/neutrino",
    ]

    /// The terminal view the app carries, for the About card.
    static let swiftTermName = "SwiftTerm"

    /// The SwiftTerm release `project.yml` pins.
    static let swiftTermVersion = "1.19.0"

    /// SwiftTerm's licence.
    static let swiftTermLicence = "MIT"

    /// SwiftTerm's source at the pinned release.
    static let swiftTermSourceUrl = "https://github.com/migueldeicaza/SwiftTerm/tree/v1.19.0"

    /// The SMB client the app carries, for the About card.
    static let amsmb2Name = "AMSMB2"

    /// The AMSMB2 release `project.yml` pins.
    static let amsmb2Version = "4.0.3"

    /// AMSMB2's licence, which the libsmb2 it builds makes its own.
    static let amsmb2Licence = "LGPL-2.1"

    /// AMSMB2's source at the pinned release.
    static let amsmb2SourceUrl = "https://github.com/amosavian/AMSMB2/tree/4.0.3"

    /// The SMB library AMSMB2 builds from its source, for the About card.
    static let libsmb2Name = "libsmb2"

    /// The libsmb2 version AMSMB2 4.0.3 builds.
    static let libsmb2Version = "6.1.0"

    /// libsmb2's licence.
    static let libsmb2Licence = "LGPL-2.1"

    /// The libsmb2 commit AMSMB2 4.0.3 builds.
    static let libsmb2Commit = "aff9fa6ba9f41cfd3c15d184554601ec3f6d8d03"  // scan: allow

    /// libsmb2's source at that commit.
    static let libsmb2SourceUrl = "https://github.com/sahlberg/libsmb2/tree/\(libsmb2Commit)"

    /// The remote desktop core the app carries, for the About card.
    static let rustDeskName = "RustDesk"

    /// The RustDesk release `packaging/build/build_core_rustdesk.py` pins.
    static let rustDeskVersion = "1.4.9"

    /// RustDesk's licence.
    static let rustDeskLicence = "AGPL-3.0"

    /// RustDesk's source at the pinned release, by edition: the mainland edition links Gitee's mirror, which holds
    /// the same tag at the same commit.
    static let rustDeskSourceUrls = [
        editionIntl: "https://github.com/rustdesk/rustdesk/tree/1.4.9",
        editionCn: "https://gitee.com/mirrors/rustdesk/tree/1.4.9",
    ]

    /// The patch the core is built with, under the app's source `{source}` at its release tag `v{version}`.
    static let rustDeskPatchUrl = "{source}/blob/v{version}/packaging/build/build_core_rustdesk.patch"

    /// How long an armed destructive button waits for its second press.
    static let armSeconds = 5.0

    /// How long a copy button shows that it copied.
    static let copiedShownSeconds = 1.5

    /// The subsystem every log line of the app is written under.
    static let logSubsystem = "io.github.iffix.neutrino"

    /// The settings key of the language.
    static let settingsKeyLanguage = "language"

    /// The settings key of the theme.
    static let settingsKeyTheme = "theme"

    /// The settings key of the local port table.
    static let settingsKeyLocalPorts = "local_ports"

    /// The settings key of each shared desktop's codec and quality.
    static let settingsKeyDesktopChoices = "rdp_choices"

    /// Where the desktop client's word catalogs are in the app's bundle.
    static let desktopLocalesDirectory = "locales"

    /// Where the app's own word catalogs are in the app's bundle.
    static let appLocalesDirectory = "app_locales"

    /// The Keychain service every secret of the app is filed under.
    static let keychainService = "io.github.iffix.neutrino"

    /// The Keychain item the bindings are kept in.
    static let bindingsAccount = "bindings"
}

/// The channel: the link, the paths, the frames' numbers and the timings of `design/protocol.md`.
enum Channel {
    // swift-format-ignore: AlwaysUseLowerCamelCase
    /// The protocol number this build speaks, under the one name it has in every package.
    static let PROTOCOL = 4

    /// What a pasted or scanned link starts with.
    static let linkPrefix = "neutrino://enroll/"

    /// The largest payload a link inflates to.
    static let linkInflatedBytesMax = 1024 * 1024

    /// The path a binding starts at, on the pinned agent port.
    static let joinPath = "/api/channel/join"

    /// The path a binding ends at.
    static let leavePath = "/api/channel/leave"

    /// The path of the one socket.
    static let socketPath = "/api/channel/socket"

    /// The name every network a hub serves resolves to that hub's address on it.
    static let hubName = "hub.neutrino.internal"

    /// How long a join or a leave may take.
    static let requestTimeoutSeconds = 10.0

    /// How long telling a hub of a leave may take, after this phone has forgotten the binding.
    static let leaveTellTimeoutSeconds = 5.0

    /// How long connecting and the handshake on top of it may take together.
    static let connectTimeoutSeconds = 10.0

    /// How often a round dials again an address that refused, until the round's connect time has passed.
    static let redialIntervalSeconds = 1.0

    /// How often a report goes up while nothing changes.
    static let reportIntervalSeconds = 30.0

    /// How long the open socket may stay silent before it counts as dead.
    static let silenceTimeoutSeconds = 45.0

    /// How often the open socket sends this phone's `ping` frame.
    static let pingIntervalSeconds = 20.0

    /// The first wait after a broken wire, doubled on each failure.
    static let backoffMinSeconds = 5.0

    /// The longest wait between two rounds, and the wait after a refusal the binding survives.
    static let backoffMaxSeconds = 60.0

    /// How long a refresh waits for a hub's state frame or a code before it ends.
    static let refreshTimeoutSeconds = 10.0

    /// How long a stream this side opened waits for the hub's close.
    static let streamTimeoutSeconds = 15.0

    /// A byte stream's credit window; half of it consumed sends the next grant.
    static let streamCreditBytes = 1024 * 1024

    /// The most one binary frame carries after its stream id.
    static let chunkBytes = 64 * 1024

    /// How long a send waits for the hub's credit.
    static let creditTimeoutSeconds = 60.0

    /// The largest message the socket takes.
    static let messageBytesMax = 4 * 1024 * 1024

    /// The longest nonce a `ping` carries.
    static let pingNonceMax = 64

    /// A socket closed from this side with nothing to say.
    static let closeNormal = 1000

    /// The close code after a `refused` frame.
    static let closeRefused = 4000

    /// The close code of a socket another socket for the same binding replaced.
    static let closeReplaced = 4010

    /// The first id this side opens a stream at; the hub's are even.
    static let firstStreamId: UInt32 = 1

    /// The step between two ids one side opens.
    static let streamIdStep: UInt32 = 2

    /// The big-endian stream id at the head of a binary frame.
    static let streamIdBytes = 4

    /// A stream for one published entry's material, or the panel's sign-in.
    static let kindService = "service"

    /// A shell on a managed machine.
    static let kindShell = "shell"

    /// A command on a managed machine, such as a shell's resize.
    static let kindCommand = "command"

    /// One TCP connection to a published entry or to the hub's panel, carried by the hub.
    static let kindConnect = "connect"

    /// The code this side closes a stream the hub opened with: a client serves no kind.
    static let codeKindUnknown = "kind_unknown"

    /// The refusal of a binding the hub does not hold.
    static let codeBindingUnknown = "binding_unknown"

    /// The refusal of a client older than the hub's floor.
    static let codeProtocolTooOld = "protocol_too_old"

    /// The refusal of a client newer than the hub.
    static let codeProtocolTooNew = "protocol_too_new"

    /// The refusal of a join while the hub has paused new enrolments; the ticket stays good.
    static let codeAdmissionPaused = "admission_paused"

    /// A certificate that is not the pinned one.
    static let codeHubUntrusted = "hub_untrusted"

    /// Anything on the way to the hub that did not answer.
    static let codeHubUnreachable = "hub_unreachable"

    /// The hub closed the socket after a refusal it did not word.
    static let codeHubRefused = "hub_refused"

    /// A fault of this app's own, with its detail.
    static let codeClientInternal = "client_internal"

    /// The ways a client's socket reaches its hub, each worded as `ui.through.<way>`.
    static let reachedThrough = ["lan", "netbird", "easytier", "ssh_relay", "direct", "sakurafrp", "openfrp"]

    /// NetBird's provider name in an overlay object.
    static let providerNetbird = "netbird"

    /// EasyTier's provider name in an overlay object.
    static let providerEasytier = "easytier"

    /// The port of an `https` address that names none.
    static let httpsDefaultPort = 443

    /// The port of an `http` address that names none.
    static let httpDefaultPort = 80

    /// Every code the hub may send this app, each worded in the catalogs.
    static let hubCodes = [
        "admission_paused",
        "agent_offline",
        "binding_unknown",
        "client_disabled",
        "connect_failed",
        "connect_limit",
        "hello_invalid",
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
        "shell_unknown",
        "ticket_spent",
        "vault_locked",
        "verb_unknown",
    ]
}

/// The loopback forwards of web pages and the hub's panel.
enum Forward {
    /// The address every forward listens on.
    static let bindHost = "127.0.0.1"

    /// The numbers a person may fix a local port to.
    static let fixedPorts = 1024...65535

    /// Where an automatic local port is looked for when the entry's own is taken; the panel starts here.
    static let autoFirstPort = 20000

    /// The most one read of a forwarded connection copies at once.
    static let bufferBytes = 65536

    /// The entry part of the panel forward's key, `<binding>/#panel`; no published entry's id holds `#`.
    static let panelEntry = "#panel"

    /// The query parameter a web page that needs a token takes it in.
    static let tokenParameter = "tkn"
}

/// The Terminals page and its tabs.
enum TerminalPage {
    /// The output a tab keeps to draw again in a new view: the agent keeps as much.
    static let keptBytes = 256 * 1024

    /// How long a tab's stream must be quiet before Clear stops dropping what arrives.
    static let clearQuietSeconds = 0.5

    /// The longest a tab drops what arrives after Clear.
    static let clearMaxSeconds = 20.0

    /// The escape byte a terminal's key sequences start with.
    static let escape: UInt8 = 0x1b

    /// The byte Ctrl+C sends.
    static let controlC: UInt8 = 0x03

    /// The point size of the terminal's font.
    static let fontSize: Double = 13

    /// The least height of the terminal's card, in points.
    static let cardMinHeight: Double = 200

    /// The sixteen ANSI colours, the same in both themes: black, red, green, yellow, blue, magenta, cyan and
    /// white, then the bright eight in the same order. The Tango palette, xterm.js's own.
    static let ansiColors: [UInt32] = [
        0x2E3436, 0xCC0000, 0x4E9A06, 0xC4A000, 0x3465A4, 0x75507B, 0x06989A, 0xD3D7CF,
        0x555753, 0xEF2929, 0x8AE234, 0xFCE94F, 0x729FCF, 0xAD7FA8, 0x34E2E2, 0xEEEEEC,
    ]

    /// The opacity of the accent the selection is drawn in.
    static let selectionOpacity = 0.25
}

/// The share page and its SMB client.
enum SharePage {
    /// The Keychain item the kept share logins are in.
    static let loginsAccount = "share_logins"

    /// How many names an upload or a new folder tries: the name itself, then ` (1)` to ` (31)`.
    static let nameAttempts = 32

    /// How long one SMB request may take.
    static let requestTimeoutSeconds = 60.0

    /// The directory under the app's temporary directory that files are read into and picked files copied to.
    static let temporaryDirectory = "share"

    /// The characters no name in a share holds.
    static let nameForbidden = "/\\:*?\"<>|"

    /// How often a pull on the list looks whether the folder's reading ended.
    static let refreshPollNanoseconds: UInt64 = 100_000_000

    /// The code of a transfer the background's close cut.
    static let codeInterrupted = "share_interrupted"

    /// The code of a login the share rejected.
    static let codeLoginRejected = "share_login_rejected"

    /// How often a running transfer's row is drawn again with the bytes the forward has carried.
    static let progressIntervalSeconds = 0.25

    /// The bytes an upload's forward carries up beyond which a part of the file is in the share: more than the
    /// requests that open the file.
    static let partWrittenBytes: Int64 = 65536

    /// The code of an item Upload from Photos picked that the picker did not hand over.
    static let codePhotoUnavailable = "share_photo_unavailable"
}

/// The app's time in the background.
enum Background {
    /// The seconds before iOS ends the background task at which every connection is closed.
    static let closeMarginSeconds = 5.0

    /// A background time longer than this is iOS saying the app is still in front.
    static let taskSecondsMax = 600.0

    /// The background time taken when iOS names none, about what iOS 16 gives.
    static let taskSecondsAssumed = 30.0
}

/// The remote desktop viewer and the RustDesk core it drives.
enum RemoteDesktop {
    /// RustDesk's peer option naming the codec a session asks for.
    static let optionCodec = "codec-preference"

    /// The core's session option naming the picture quality, kept in the peer's `image_quality`.
    static let optionQuality = "image-quality"

    /// RustDesk's mouse event type in the low three bits of a mask: the pointer moved.
    static let mouseMove = 0

    /// RustDesk's mouse event type: a button pressed.
    static let mouseDown = 1

    /// RustDesk's mouse event type: a button released.
    static let mouseUp = 2

    /// RustDesk's mouse event type: the wheel turned; the event's y carries the steps.
    static let mouseWheel = 3

    /// The left button, above the type bits of a mask.
    static let mouseLeft = 1 << 3

    /// The right button, above the type bits of a mask.
    static let mouseRight = 2 << 3

    /// The finger travel, in points, of one wheel step in a two-finger scroll.
    static let scrollStepPoints = 9.0

    /// The change in finger spread, or the move of the fingers' centre, in points, that decides what a two-finger
    /// gesture is.
    static let pinchSlopPoints = 9.0

    /// The largest zoom a pinch reaches, over the picture fitted to the viewer.
    static let zoomMax = 6.0

    /// The RustDesk core's state: logged in, frames follow.
    static let stateConnected = 1

    /// The RustDesk core's state: the machine refused the password.
    static let stateLoginFailed = 2

    /// The RustDesk core's state: the connection ended.
    static let stateClosed = 3

    /// The pause between two typed characters, so a Linux desktop types one before the next arrives.
    static let typePaceSeconds = 0.04

    /// The last character of ASCII; text with any character above it goes to a Linux host as a paste.
    static let asciiLast: UInt32 = 0x7F

    /// The `platform_os` a desktop entry carries when the sharing machine runs Linux.
    static let platformOsLinux = "linux"

    /// The `platform_os` a desktop entry carries when the sharing machine is a Mac.
    static let platformOsDarwin = "darwin"

    /// The directory under the app's Application Support where the core keeps its configuration.
    static let coreDirectory = "rustdesk"
}
