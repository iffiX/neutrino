import SwiftUI
import UIKit
import XCTest

@testable import Neutrino

/// Draws the terminal, the remote desktop viewer, the Settings page and a share's login sheet into PNG files in the
/// directory `NEUTRINO_SCREENS` names, for a look by eye; skipped while it names none.
final class ScreenshotTests: XCTestCase {
    private static let sample: String = {
        var text = "\u{1b}[0mbackgrounds 40-47, then 100-107\r\n"
        for code in 40...47 { text += "\u{1b}[\(code)m \(code - 40) " }
        text += "\u{1b}[0m\r\n"
        for code in 100...107 { text += "\u{1b}[\(code)m \(code - 92) " }
        text += "\u{1b}[0m\r\ntext 30-37, then 90-97\r\n"
        for code in 30...37 { text += "\u{1b}[\(code)m \(code - 30) " }
        text += "\u{1b}[0m\r\n"
        for code in 90...97 { text += "\u{1b}[\(code)m \(code - 82) " }
        text += "\u{1b}[0m\r\n\r\n"
        text += "\u{1b}[44;97m ~/src \u{1b}[0m \u{1b}[40;32m ✔ \u{1b}[0m \u{1b}[43;30m 5s \u{1b}[0m"
        text += " \u{1b}[47;30m 14:23:05 \u{1b}[0m\r\n"
        text += "\u{1b}[48;5;236;38;5;31m ~/src \u{1b}[38;5;76m✔ \u{1b}[38;5;101m5s "
        text += "\u{1b}[38;5;66m14:23:05 \u{1b}[0m\r\n"
        text += "\u{1b}[1;34mdocs\u{1b}[0m  \u{1b}[1;32mbuild.sh\u{1b}[0m  \u{1b}[1;36mlink\u{1b}[0m  README.md\r\n"
        text += "plain text on the theme's background\r\n"
        text += "\u{1b}[1;32miffi@nmxrel\u{1b}[0m:\u{1b}[1;34m~\u{1b}[0m$ "
        return text
    }()

    private static let services: [JSONValue] = [
        web("gitea", "Gitea", "http://nmxrel:3000/"),
        web("vscode", "VS Code (lab)", "http://nmxrel:3201/"),
        web("cloudcli", "CloudCLI (demo)", "http://nmxrel:3002/"),
        web("codeg", "Codeg (lab)", "http://nmxrel:3101/"),
        web("antigravity", "Antigravity (direct)", "http://192.168.122.132:49723/", isHealthy: false),
        file("share", "share", host: "192.168.122.46", machine: "nmxwin"),
        file("music", "music, the long library share of the house", host: "nmxrel", machine: "nmxrel"),
        desktop("nmxwin", "nmxwin", host: "192.168.122.46", platform: "windows"),
        desktop("mac", "mac", host: "192.168.122.50", platform: "darwin"),
    ]

    private static let machines: [JSONValue] = [
        machine("nmxrel", isOnline: true), machine("mac", isOnline: false), machine("nmxwin", isOnline: true),
    ]

    private let words = WordCatalog.load(language: "en", bundle: Bundle(for: ClientCore.self))
    private var window: UIWindow?

    override func tearDown() {
        window?.isHidden = true
        window = nil
    }

    func testOneTerminalRepaintedInEachTheme() throws {
        let directory = try directory()
        let tabs = TerminalTabs(open: { _, _, _, _ in .failure(.refusal("hub_unreachable")) }, clock: FakeClientClock())
        let sessionId = tabs.create(bindingId: "hub", deviceId: "nmxrel", name: "nmxrel")
        let cache = TerminalViewCache(tabs: tabs)
        let controller = UIViewController()
        let terminal: UIView = cache.view(of: sessionId)
        controller.view.addSubview(terminal)
        let screen = try screenSize()
        let shown = try show(controller, .dark, size: screen)
        terminal.frame = CGRect(
            x: 8, y: shown.safeAreaInsets.top + 12, width: shown.bounds.width - 16, height: shown.bounds.height * 0.55)
        tabs.onOutput?(sessionId, Data(Self.sample.utf8))
        for (name, palette) in [("terminal_dark", NeutrinoPalette.dark), ("terminal_light", NeutrinoPalette.light)] {
            shown.overrideUserInterfaceStyle = palette.isDark ? .dark : .light
            controller.view.backgroundColor = UIColor(palette.surface)
            cache.paint(palette)
            settle()
            try save(shown, name, in: directory)
        }
    }

    func testTheRemoteDesktopViewerMovesThePictureAboveTheKeyBar() throws {
        let directory = try directory()
        let screen = try screenSize()
        try viewer(size: screen, keyboardHeight: 336, name: "viewer_portrait", in: directory)
        let landscape = CGSize(width: screen.height, height: screen.width)
        try viewer(size: landscape, keyboardHeight: 209, name: "viewer_landscape", in: directory)
    }

    func testTheSettingsPageInBothThemes() throws {
        let directory = try directory()
        let screen = try screenSize()
        let suite = "neutrino.screens.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let core = makeCore(defaults)
        for (name, palette) in [("settings_light", NeutrinoPalette.light), ("settings_dark", NeutrinoPalette.dark)] {
            let page = VStack(spacing: 0) {
                TopBar(title: core.words.word(AppScreen.settings.titleKey), onBack: nil, isRefreshing: false) {}
                SettingsScreen(core: core)
            }
            .background(palette.bg.ignoresSafeArea())
            .environment(\.palette, palette)
            .environment(\.words, core.words)
            let shown = try show(UIHostingController(rootView: page), palette.isDark ? .dark : .light, size: screen)
            try save(shown, name, in: directory)
        }
    }

    func testTheShareLoginSheetWithSeveralUsersInBothThemes() throws {
        let directory = try directory()
        let screen = try screenSize()
        let suite = "neutrino.screens.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let core = makeCore(defaults)
        let target = ShareTarget(
            bindingId: "hub", entryId: "music", title: "music", share: "music", users: ["iffi", "guest"])
        for (name, palette) in [("login_light", NeutrinoPalette.light), ("login_dark", NeutrinoPalette.dark)] {
            let sheet = ShareLoginSheet(core: core, target: target)
                .environment(\.palette, palette)
                .environment(\.words, core.words)
            let shown = try show(UIHostingController(rootView: sheet), palette.isDark ? .dark : .light, size: screen)
            try save(shown, name, in: directory)
        }
    }

    func testTheWebFilesAndDesktopsListsPutEveryRowsButtonsUnderItsText() throws {
        let directory = try directory()
        let screen = try screenSize()
        let suite = "neutrino.screens.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let core = try connectedCore(defaults)
        let pages: [(String, AppScreen, AnyView)] = [
            ("list_web", .web, AnyView(WebScreen(core: core))),
            ("list_files", .files, AnyView(FilesScreen(core: core))),
            ("list_desktops", .desktops, AnyView(RemoteDesktopScreen(core: core))),
        ]
        for (name, bar, page) in pages {
            let shown = try show(UIHostingController(rootView: portrait(page, bar, core: core)), .light, size: screen)
            try save(shown, name, in: directory)
        }
    }

    func testTheTerminalsPageHasItsKeyRowAndNewTerminalWithNoKeyboard() throws {
        let directory = try directory()
        let screen = try screenSize()
        let suite = "neutrino.screens.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let core = try connectedCore(defaults)
        let cache = TerminalViewCache(tabs: core.tabs)
        let bindingId = try XCTUnwrap(core.hubs.first?.binding.id)
        core.pickMachine(TerminalMachine(bindingId: bindingId, deviceId: "nmxrel"))
        core.newTerminal()
        let page = portrait(TerminalScreen(core: core, cache: cache), .terminals, core: core)
        let shown = try show(UIHostingController(rootView: page), .light, size: screen)
        core.tabs.onOutput?(core.activeTab, Data(Self.sample.utf8))
        settle()
        try save(shown, "terminals_key_row", in: directory)
    }

    func testTheSidebarLayoutInLandscapeWithTheHousingOnEitherSide() throws {
        let directory = try directory()
        let suite = "neutrino.screens.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let core = try connectedCore(defaults)
        let cache = TerminalViewCache(tabs: core.tabs)
        defer { _ = try? turn(to: .portrait) }
        let sides: [(String, UIInterfaceOrientation)] = [
            ("landscape_housing_left", .landscapeRight), ("landscape_housing_right", .landscapeLeft),
        ]
        for (name, orientation) in sides {
            guard try turn(to: orientation) else { throw XCTSkip("the Simulator did not turn for \(name)") }
            let size = try screenSize()
            let shell = AppShell(core: core, cache: cache)
                .environment(\.palette, .light)
                .environment(\.words, core.words)
                .environmentObject(ArmState())
            let shown = try show(UIHostingController(rootView: shell), .light, size: size)
            try save(shown, name, in: directory)
        }
    }

    private func makeCore(_ defaults: UserDefaults, transport: FakeHubTransport = FakeHubTransport()) -> ClientCore {
        ClientCore(
            secrets: FakeSecretStore(), transport: transport, clock: FakeClientClock(), defaults: defaults,
            device: Samples.device, edition: Client.editionIntl, hasNetwork: { true }, resolveHubName: { $0(nil) },
            localNetworks: { [] }, shareClient: { FakeShareClient() }, remoteDesktop: FakeRemoteDesktopCore(),
            bundle: Bundle(for: ClientCore.self))
    }

    private func connectedCore(_ defaults: UserDefaults) throws -> ClientCore {
        let transport = FakeHubTransport()
        let core = makeCore(defaults, transport: transport)
        core.join(
            Samples.link([
                "urls": .array([.string("https://192.168.1.1:8443")]), "token": .string("TICKET"),
                "fp": .string(Samples.fingerprint), "role": .string("client"),
            ]))
        let socket = try XCTUnwrap(transport.sockets.first)
        socket.deliver(.opened)
        transport.posts.first?.completion(.success(["id": .string("hub-binding"), "token": .string("tok")]))
        socket.deliver(frame: Samples.welcome)
        socket.deliver(frame: Samples.state(["services": .array(Self.services), "terminals": .array(Self.machines)]))
        return core
    }

    private func portrait<Page: View>(_ page: Page, _ bar: AppScreen, core: ClientCore) -> some View {
        VStack(spacing: 0) {
            TopBar(title: core.words.word(bar.titleKey), onBack: nil, isRefreshing: false) {}
            page.frame(maxWidth: .infinity, maxHeight: .infinity)
            PageBar(isSidebar: false, selected: .constant(bar))
        }
        .background(NeutrinoPalette.light.bg.ignoresSafeArea())
        .environment(\.palette, .light)
        .environment(\.words, core.words)
        .environmentObject(ArmState())
    }

    private func turn(to orientation: UIInterfaceOrientation) throws -> Bool {
        let scene = try scene()
        let masks: [UIInterfaceOrientation: UIInterfaceOrientationMask] = [
            .portrait: .portrait, .landscapeLeft: .landscapeLeft, .landscapeRight: .landscapeRight,
        ]
        scene.requestGeometryUpdate(.iOS(interfaceOrientations: masks[orientation] ?? .portrait))
        RunLoop.main.run(until: Date().addingTimeInterval(2))
        return scene.effectiveGeometry.interfaceOrientation == orientation
    }

    private func viewer(size: CGSize, keyboardHeight: Double, name: String, in directory: URL) throws {
        let core = PictureRemoteDesktopCore()
        let target = RemoteDesktopTarget(
            key: "hub/desk", name: "Home:nmxwin", host: "127.0.0.1", port: 20000, password: "")
        let model = RemoteDesktopViewerModel(target: target, core: core, clock: FakeClientClock())
        let page = RemoteDesktopViewer(model: model, onClose: {})
            .environment(\.palette, .dark)
            .environment(\.words, words)
        let shown = try show(UIHostingController(rootView: page), .dark, size: size)
        let picture = UIImageView(image: core.picture)
        picture.frame = model.frameView.bounds
        picture.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        model.frameView.addSubview(picture)
        settle()
        try save(shown, "\(name)_1_picture_alone", in: directory)

        model.press(.keys, onClose: {})
        let keyboard = CGRect(x: 0, y: size.height - keyboardHeight, width: size.width, height: keyboardHeight)
        NotificationCenter.default.post(
            name: UIResponder.keyboardWillChangeFrameNotification, object: nil,
            userInfo: [UIResponder.keyboardFrameEndUserInfoKey: NSValue(cgRect: keyboard)])
        shown.addSubview(simulatedKeyboard(keyboard))
        settle()
        try save(shown, "\(name)_2_keyboard_and_key_bar", in: directory)

        let viewport = model.viewport
        XCTAssertGreaterThan(viewport.covered, keyboardHeight)
        XCTAssertLessThanOrEqual(viewport.top + viewport.drawnHeight, viewport.viewHeight - viewport.covered + 0.5)
    }

    private func directory() throws -> URL {
        let path = ProcessInfo.processInfo.environment["NEUTRINO_SCREENS"] ?? ""
        if path.isEmpty { throw XCTSkip("NEUTRINO_SCREENS names no directory") }
        let url = URL(fileURLWithPath: path, isDirectory: true)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }

    private func scene() throws -> UIWindowScene {
        try XCTUnwrap(UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first)
    }

    private func screenSize() throws -> CGSize {
        try scene().screen.bounds.size
    }

    private func show(_ controller: UIViewController, _ style: UIUserInterfaceStyle, size: CGSize) throws -> UIWindow {
        window?.isHidden = true
        let shown = UIWindow(windowScene: try scene())
        shown.frame = CGRect(origin: .zero, size: size)
        shown.overrideUserInterfaceStyle = style
        shown.windowLevel = .alert + 1
        shown.rootViewController = controller
        shown.makeKeyAndVisible()
        window = shown
        settle()
        return shown
    }

    private func settle() {
        RunLoop.main.run(until: Date().addingTimeInterval(0.8))
    }

    private func save(_ shown: UIWindow, _ name: String, in directory: URL) throws {
        let image = UIGraphicsImageRenderer(bounds: shown.bounds).image { _ in
            _ = shown.drawHierarchy(in: shown.bounds, afterScreenUpdates: true)
        }
        try XCTUnwrap(image.pngData()).write(to: directory.appendingPathComponent("\(name).png"))
    }

    private static func web(_ id: String, _ title: String, _ url: String, isHealthy: Bool = true) -> JSONValue {
        .object([
            "id": .string(id), "type": .string("web"), "title": .string(title), "source": .string("module"),
            "payload": .object(["url": .string(url)]), "device_name": .string("nmxrel"), "is_healthy": .bool(isHealthy),
        ])
    }

    private static func file(_ id: String, _ title: String, host: String, machine: String) -> JSONValue {
        .object([
            "id": .string(id), "type": .string("file"), "title": .string(title), "source": .string("module"),
            "payload": .object([
                "protocol": .string("smb"), "host": .string(host), "share": .string(id),
                "users": .array([.string("lab")]),
            ]),
            "device_name": .string(machine),
        ])
    }

    private static func desktop(_ id: String, _ title: String, host: String, platform: String) -> JSONValue {
        .object([
            "id": .string(id), "type": .string("rdp"), "title": .string(title), "source": .string("device"),
            "payload": .object([
                "host": .string(host), "port": .int(21118), "platform_os": .string(platform),
            ]),
            "device_name": .string(title),
        ])
    }

    private static func machine(_ name: String, isOnline: Bool) -> JSONValue {
        .object(["device_id": .string(name), "name": .string(name), "is_online": .bool(isOnline)])
    }

    private func simulatedKeyboard(_ frame: CGRect) -> UIView {
        let keyboard = UILabel(frame: frame)
        keyboard.backgroundColor = UIColor(white: 0.2, alpha: 1)
        keyboard.textColor = UIColor(white: 0.75, alpha: 1)
        keyboard.textAlignment = .center
        keyboard.text = "simulated keyboard"
        return keyboard
    }
}
