import SwiftUI
import UIKit
import XCTest

@testable import Neutrino

/// Draws the terminal, the remote desktop viewer and the Settings page into PNG files in the directory
/// `NEUTRINO_SCREENS` names, for a look by eye; skipped while it names none.
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
        let core = ClientCore(
            secrets: FakeSecretStore(), transport: FakeHubTransport(), clock: FakeClientClock(), defaults: defaults,
            device: Samples.device, edition: Client.editionIntl, hasNetwork: { true }, resolveHubName: { $0(nil) },
            localNetworks: { [] }, shareClient: { FakeShareClient() }, remoteDesktop: FakeRemoteDesktopCore(),
            bundle: Bundle(for: ClientCore.self))
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

    private func simulatedKeyboard(_ frame: CGRect) -> UIView {
        let keyboard = UILabel(frame: frame)
        keyboard.backgroundColor = UIColor(white: 0.2, alpha: 1)
        keyboard.textColor = UIColor(white: 0.75, alpha: 1)
        keyboard.textAlignment = .center
        keyboard.text = "simulated keyboard"
        return keyboard
    }
}
