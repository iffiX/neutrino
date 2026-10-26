import SwiftUI
import UIKit
import XCTest

@testable import Neutrino

/// Draws the terminal, the remote desktop viewer, the pages and the frame into PNG files, and records the Terminals
/// page as it moves, in the directory `NEUTRINO_SCREENS` names, for a look by eye; skipped while it names none.
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
        web("gitea", "Gitea", "http://nmxrel:3000/", port: 24001),
        port("gitea_ssh", "Gitea SSH", app: "gitea", port: 24002),
        web("hermes", "Hermes WebUI", "http://nmxwin:8787/", port: 24003, machine: "nmxwin", isTokenRequired: true),
        port("postgres", "Postgres", app: "postgres", port: 24004),
        file("share", "share", host: "192.168.122.46", machine: "nmxwin"),
        file("music", "music, the long library share of the house", host: "nmxrel", machine: "nmxrel"),
        desktop("nmxwin", "nmxwin", host: "192.168.122.46", platform: "windows"),
        desktop("nmxrel", "nmxrel", host: "192.168.122.41", platform: "linux"),
    ]

    private static let apps: [JSONValue] = [
        app("gitea", "Gitea", source: "module", machine: "nmxrel"),
        app("hermes", "Hermes WebUI", source: "module", machine: "nmxwin"),
        app("postgres", "Postgres", source: "declared", machine: "nmxrel"),
    ]

    private static let machines: [JSONValue] = [
        machine("nmxrel", isOnline: true), machine("nmxwin", isOnline: true),
    ]

    private let words = WordCatalog.load(language: "en", bundle: Bundle(for: ClientCore.self))
    private var window: UIWindow?

    override func tearDown() {
        window?.isHidden = true
        window = nil
    }

    func testOneTerminalRepaintedInEachTheme() throws {
        let directory = try directory()
        let tabs = TerminalTabs(hubOf: { _ in nil }, clock: FakeClientClock())
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

    func testTheAppsPageInBothThemesWithOneAppInUse() throws {
        let directory = try directory()
        let screen = try screenSize()
        let suite = "neutrino.screens.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let core = try connectedCore(defaults)
        let hub = try XCTUnwrap(core.hubs.first)
        try useGitea(core)
        for (name, palette) in [("apps_light", NeutrinoPalette.light), ("apps_dark", NeutrinoPalette.dark)] {
            let page = VStack(spacing: 0) {
                TopBar(title: core.words.word(AppScreen.apps.titleKey), onBack: nil, isRefreshing: false) {}
                AppsScreen(core: core).frame(maxWidth: .infinity, maxHeight: .infinity)
                PageBar(isSidebar: false, selected: .constant(AppScreen.apps))
            }
            .background(palette.bg.ignoresSafeArea())
            .environment(\.palette, palette)
            .environment(\.words, core.words)
            .environmentObject(ArmState())
            let shown = try show(UIHostingController(rootView: page), palette.isDark ? .dark : .light, size: screen)
            try save(shown, name, in: directory)
        }
        let entries = AppForwards.entries(of: hub, app: try XCTUnwrap(hub.apps.first))
        let target = LocalPortTarget(bindingId: hub.binding.id, appId: "gitea", title: "Gitea", entries: entries)
        let dialog = LocalPortDialog(core: core, target: target)
            .environment(\.palette, NeutrinoPalette.light)
            .environment(\.words, core.words)
        let shown = try show(UIHostingController(rootView: dialog), .light, size: screen)
        try save(shown, "apps_configure", in: directory)
        core.stopApp(bindingId: hub.binding.id, appId: "gitea")
    }

    func testTheAppsFilesAndDesktopsListsPutEveryRowsButtonsUnderItsText() throws {
        let directory = try directory()
        let screen = try screenSize()
        let suite = "neutrino.screens.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let core = try connectedCore(defaults)
        let pages: [(String, AppScreen, AnyView)] = [
            ("list_apps", .apps, AnyView(AppsScreen(core: core))),
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
        try save(shown, "terminals_1_top_new_terminal", in: directory)
        scrollToEnd(shown)
        settle()
        try save(shown, "terminals_2_scrolled_key_row", in: directory)
    }

    func testTheTerminalsStatusLineButtonsAndTheKeyboard() throws {
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
        let shell = AppShell(core: core, cache: cache, screen: .terminals)
            .environment(\.palette, .light)
            .environment(\.words, core.words)
            .environmentObject(ArmState())
        let shown = try show(UIHostingController(rootView: shell), .light, size: screen)
        core.tabs.onOutput?(core.activeTab, Data(Self.sample.utf8))
        settle()
        scrollToEnd(shown)
        settle()
        try save(shown, "terminals_3_keyboard_and_keys_buttons", in: directory)

        cache.keys.toggleRow()
        settle()
        try save(shown, "terminals_4_key_row_hidden", in: directory)
        cache.keys.toggleRow()

        cache.openKeyboard(on: core.activeTab)
        XCTAssertTrue(isTrue { cache.focus.isKeyboardShown }, "no software keyboard came up")
        settle()
        try screenOfSimulator("terminals_5_keyboard_from_its_button", in: directory)
        KeyboardClosingLayer.close()
        XCTAssertTrue(isTrue { !cache.focus.isKeyboardShown }, "the keyboard stayed up")
        settle()
        try screenOfSimulator("terminals_6_keyboard_closed", in: directory)
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

    func testTheSidebarLayoutOnTerminalsJoinAndAShare() throws {
        let directory = try directory()
        let suite = "neutrino.screens.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let core = try connectedCore(defaults)
        let cache = TerminalViewCache(tabs: core.tabs)
        let bindingId = try XCTUnwrap(core.hubs.first?.binding.id)
        core.pickMachine(TerminalMachine(bindingId: bindingId, deviceId: "nmxrel"))
        core.newTerminal()
        defer { _ = try? turn(to: .portrait) }
        guard try turn(to: .landscapeRight) else { throw XCTSkip("the Simulator did not turn") }
        let size = try screenSize()
        for (name, screen) in [("landscape_terminals", AppScreen.terminals), ("landscape_join", .join)] {
            let shell = AppShell(core: core, cache: cache, screen: screen)
                .environment(\.palette, .light)
                .environment(\.words, core.words)
                .environmentObject(ArmState())
            let shown = try show(UIHostingController(rootView: shell), .light, size: size)
            if screen == .terminals {
                core.tabs.onOutput?(core.activeTab, Data(Self.sample.utf8))
                settle()
            }
            try save(shown, name, in: directory)
        }

        let hub = try XCTUnwrap(core.hubs.first)
        let entry = try XCTUnwrap(hub.services.first { $0.id == "music" })
        var target = try XCTUnwrap(ShareTarget.of(hub, entry))
        target.isDeclared = true
        core.shares.logIn(target, login: ShareLogin(user: "lab", password: "pw"), isKept: false)
        XCTAssertNotNil(core.share, "the share did not open")
        let shell = AppShell(core: core, cache: cache, screen: .files)
            .environment(\.palette, .light)
            .environment(\.words, core.words)
            .environmentObject(ArmState())
        let shown = try show(UIHostingController(rootView: shell), .light, size: size)
        try save(shown, "landscape_share_plus", in: directory)
    }

    func testTheTerminalsPageStaysAtItsEndAsTheKeyboardComesAndGoes() throws {
        let screen = try screenSize()
        let suite = "neutrino.screens.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let core = try connectedCore(defaults)
        let cache = TerminalViewCache(tabs: core.tabs)
        let bindingId = try XCTUnwrap(core.hubs.first?.binding.id)
        core.pickMachine(TerminalMachine(bindingId: bindingId, deviceId: "nmxrel"))
        core.newTerminal()
        let shell = AppShell(core: core, cache: cache, screen: .terminals)
            .environment(\.palette, .light)
            .environment(\.words, core.words)
            .environmentObject(ArmState())
        let shown = try show(UIHostingController(rootView: shell), .light, size: screen)
        let scroll = try XCTUnwrap(pageScroll(in: shown))
        XCTAssertLessThan(scroll.contentOffset.y, end(of: scroll), "the page has nothing above its end")

        cache.openKeyboard(on: core.activeTab)
        guard isTrue({ cache.focus.isKeyboardShown }) else { throw XCTSkip("no software keyboard came up") }
        XCTAssertTrue(
            isTrue { !cache.keyboard.isMoving && cache.keyboard.overlap > 100 },
            "the slide did not end: \(cache.keyboard.overlap), \(cache.keyboard.isMoving)")
        settle()
        XCTAssertEqual(
            scroll.contentOffset.y, end(of: scroll), accuracy: 1,
            "with the keyboard covering \(cache.keyboard.overlap), the page is not at its end")

        KeyboardClosingLayer.close()
        XCTAssertTrue(
            isTrue { !cache.keyboard.isMoving && cache.keyboard.overlap == 0 },
            "the slide did not end: \(cache.keyboard.overlap), \(cache.keyboard.isMoving)")
        settle()
        XCTAssertEqual(
            scroll.contentOffset.y, end(of: scroll), accuracy: 1, "with the keyboard gone, the page left its end")
    }

    func testTheTerminalCardMovesAsOneWithTheKeyboardAndTheKeyRow() throws {
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
        let shell = AppShell(core: core, cache: cache, screen: .terminals)
            .environment(\.palette, .light)
            .environment(\.words, core.words)
            .environmentObject(ArmState())
        let shown = try show(UIHostingController(rootView: shell), .light, size: screen)
        core.tabs.onOutput?(core.activeTab, Data(Self.sample.utf8))
        cache.openKeyboard(on: core.activeTab)
        XCTAssertTrue(isTrue { cache.focus.isKeyboardShown }, "no software keyboard came up")
        KeyboardClosingLayer.close()
        XCTAssertTrue(isTrue { !cache.focus.isKeyboardShown }, "the keyboard stayed up")
        settle()
        scrollToEnd(shown)
        settle()

        let isUp = { cache.focus.isKeyboardShown && !cache.keyboard.isMoving && cache.keyboard.overlap > 100 }
        let isDown = { !cache.focus.isKeyboardShown && !cache.keyboard.isMoving && cache.keyboard.overlap == 0 }
        let steps: [(String, () -> Void, () -> Bool)] = [
            ("terminals_motion_1_keyboard_on", { cache.openKeyboard(on: core.activeTab) }, isUp),
            ("terminals_motion_2_keys_off", { cache.keys.toggleRow() }, isUp),
            ("terminals_motion_3_keys_on", { cache.keys.toggleRow() }, isUp),
            ("terminals_motion_4_keyboard_off", { KeyboardClosingLayer.close() }, isDown),
            ("terminals_motion_5_keys_off_no_keyboard", { cache.keys.toggleRow() }, isDown),
            ("terminals_motion_6_keys_on_no_keyboard", { cache.keys.toggleRow() }, isDown),
        ]
        for (name, step, isAtRest) in steps {
            try recordingOfSimulator(name, in: directory) {
                RunLoop.main.run(until: Date().addingTimeInterval(0.5))
                step()
                XCTAssertTrue(
                    isTrue(isAtRest),
                    "the slide of \(name) did not end: \(cache.keyboard.overlap), \(cache.keyboard.isMoving)")
                RunLoop.main.run(until: Date().addingTimeInterval(1.5))
            }
        }
    }

    private func useGitea(_ core: ClientCore) throws {
        let hub = try XCTUnwrap(core.hubs.first)
        core.useApp(bindingId: hub.binding.id, app: try XCTUnwrap(hub.apps.first { $0.id == "gitea" }))
        XCTAssertTrue(isTrue { core.forwardRows[AppForwards.key(hub.binding.id, "gitea")]?.isInUse == true })
    }

    func testEveryPageInChineseInBothThemes() throws {
        let directory = try directory()
        let screen = try screenSize()
        let suite = "neutrino.screens.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let core = try connectedCore(defaults)
        try useGitea(core)
        let cache = TerminalViewCache(tabs: core.tabs)
        let bindingId = try XCTUnwrap(core.hubs.first?.binding.id)
        core.pickMachine(TerminalMachine(bindingId: bindingId, deviceId: "nmxrel"))
        core.newTerminal()
        let pages: [(String, AppScreen)] = [
            ("hubs", .hubs), ("apps", .apps), ("files", .files), ("terminals", .terminals),
            ("desktops", .desktops), ("settings", .settings),
        ]
        for (theme, palette) in [("light", NeutrinoPalette.light), ("dark", NeutrinoPalette.dark)] {
            core.save(ClientSettings(language: "zh-CN", theme: theme))
            for (name, page) in pages {
                let shell = AppShell(core: core, cache: cache, screen: page)
                    .environment(\.palette, palette)
                    .environment(\.words, core.words)
                    .environmentObject(ArmState())
                let shown = try show(
                    UIHostingController(rootView: shell), palette.isDark ? .dark : .light, size: screen)
                if page == .terminals {
                    core.tabs.onOutput?(core.activeTab, Data(Self.sample.utf8))
                    settle()
                }
                try save(shown, "ios_\(name)_zh-CN_\(theme)", in: directory)
            }
            let hub = try XCTUnwrap(core.hubs.first)
            let app = try XCTUnwrap(hub.apps.first { $0.id == "hermes" })
            let target = LocalPortTarget(
                bindingId: hub.binding.id, appId: app.id, title: app.title,
                entries: AppForwards.entries(of: hub, app: app))
            let dialog = LocalPortDialog(core: core, target: target)
                .environment(\.palette, palette)
                .environment(\.words, core.words)
            let shown = try show(UIHostingController(rootView: dialog), palette.isDark ? .dark : .light, size: screen)
            try save(shown, "ios_configure_zh-CN_\(theme)", in: directory)
        }
    }

    private func makeCore(_ defaults: UserDefaults, transport: FakeTransport = FakeTransport()) -> ClientCore {
        ClientCore(
            secrets: FakeSecretStore(),
            transport: ClientTransport(
                library: transport, directory: "/data", dialerOf: { _ in transport }, clock: FakeClientClock()),
            clock: FakeClientClock(), defaults: defaults, device: Samples.device, edition: Client.editionIntl,
            hasNetwork: { true }, resolveHubName: { $0(nil) }, localNetworks: { [] },
            shareClient: { FakeShareClient() }, remoteDesktop: FakeRemoteDesktopCore(),
            bundle: Bundle(for: ClientCore.self))
    }

    private func connectedCore(_ defaults: UserDefaults) throws -> ClientCore {
        let transport = FakeTransport()
        transport.answer = { line in
            switch line.text("command") {
            case "join": return ["binding_id": .string("hub-binding"), "token": .string("tok")]
            case "forward_start": return ["listen": line["listen"] ?? .string("")]
            default: return [:]
            }
        }
        let core = makeCore(defaults, transport: transport)
        core.join(
            Samples.link([
                "urls": .array([.string("tcp://192.168.1.1:8443")]), "token": .string("TICKET"),
                "key": .string(Samples.hubKey), "role": .string("client"),
            ]))
        let id = try XCTUnwrap(core.joining.joinedId)
        XCTAssertTrue(isTrue { !transport.sent("dial").isEmpty })
        transport.event("session_open", id, ["address": .string("tcp://192.168.1.1:8443"), "path": .string("lan")])
        XCTAssertTrue(isTrue { !transport.written("hello").isEmpty })
        transport.frame(id, Samples.welcome)
        transport.frame(
            id,
            Samples.state([
                "services": .array(Self.services), "apps": .array(Self.apps), "terminals": .array(Self.machines),
            ]))
        XCTAssertTrue(isTrue { core.hubs.first?.apps.count == Self.apps.count })
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

    private func isTrue(within seconds: Double = 10, _ condition: () -> Bool) -> Bool {
        let end = Date().addingTimeInterval(seconds)
        while !condition() && Date() < end {
            RunLoop.main.run(until: Date().addingTimeInterval(0.1))
        }
        return condition()
    }

    /// Ask the CI job for a screenshot of the whole Simulator screen, the keyboard's window with it: the job takes
    /// one for every `<name>.shot` file in the directory, as `<name>.png`.
    private func screenOfSimulator(_ name: String, in directory: URL) throws {
        let asked = directory.appendingPathComponent("\(name).shot")
        let taken = directory.appendingPathComponent("\(name).png")
        try Data().write(to: asked)
        let isTaken = isTrue(within: 60) { FileManager.default.fileExists(atPath: taken.path) }
        XCTAssertTrue(isTaken, "no screenshot came for \(name)")
    }

    /// Ask the CI job to record the whole Simulator screen while `body` runs: the job starts a recording, as
    /// `<name>.mp4`, for a `<name>.rec` file and answers with `<name>.recording` once it has started, and stops it
    /// for a `<name>.stop` file and answers with `<name>.stopped` once it has ended; it gives up on either after 120
    /// seconds.
    private func recordingOfSimulator(_ name: String, in directory: URL, _ body: () -> Void) throws {
        let started = directory.appendingPathComponent("\(name).recording")
        let stopped = directory.appendingPathComponent("\(name).stopped")
        try Data().write(to: directory.appendingPathComponent("\(name).rec"))
        let isStarted = isTrue(within: 180) { FileManager.default.fileExists(atPath: started.path) }
        XCTAssertTrue(isStarted, "no recording for \(name)")
        guard isStarted else { return }
        body()
        try Data().write(to: directory.appendingPathComponent("\(name).stop"))
        let isStopped = isTrue(within: 180) { FileManager.default.fileExists(atPath: stopped.path) }
        XCTAssertTrue(isStopped, "\(name) did not stop")
    }

    /// Scroll the page's scroll view to its end, as a person does to reach the key row.
    private func scrollToEnd(_ shown: UIWindow) {
        guard let scroll = pageScroll(in: shown) else { return }
        scroll.setContentOffset(CGPoint(x: 0, y: end(of: scroll)), animated: false)
    }

    /// The page's scroll view: the outermost that scrolls.
    private func pageScroll(in shown: UIWindow) -> UIScrollView? {
        var found: [UIView] = [shown]
        while let view = found.first {
            found.removeFirst()
            if let scroll = view as? UIScrollView, scroll.contentSize.height > scroll.bounds.height {
                return scroll
            }
            found += view.subviews
        }
        return nil
    }

    private func end(of scroll: UIScrollView) -> CGFloat {
        scroll.contentSize.height - scroll.bounds.height + scroll.adjustedContentInset.bottom
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

    private static func web(
        _ id: String, _ title: String, _ url: String, port: Int, machine: String = "nmxrel",
        isTokenRequired: Bool = false
    ) -> JSONValue {
        .object([
            "id": .string(id), "type": .string("web"), "title": .string(title), "source": .string("module"),
            "payload": .object(["url": .string(url), "is_token_required": .bool(isTokenRequired)]),
            "device_name": .string(machine), "is_healthy": .bool(true), "app_id": .string(id),
            "name": .string("http"), "local_port": .int(port),
        ])
    }

    private static func port(_ id: String, _ title: String, app: String, port: Int) -> JSONValue {
        .object([
            "id": .string(id), "type": .string("port"), "title": .string(title), "source": .string("module"),
            "payload": .object(["host": .string("nmxrel"), "port": .int(5432), "protocol": .string("tcp")]),
            "device_name": .string("nmxrel"), "app_id": .string(app), "name": .string("tcp"),
            "local_port": .int(port),
        ])
    }

    private static func app(_ id: String, _ title: String, source: String, machine: String) -> JSONValue {
        .object([
            "id": .string(id), "title": .string(title), "source": .string(source),
            "device_id": .string(machine), "device_name": .string(machine),
            "local_name": .string(machine.isEmpty ? "\(id).localhost" : "\(id).\(machine).localhost"),
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
        .object([
            "device_id": .string(name), "name": .string(name), "is_online": .bool(isOnline),
            "accounts": .array([.string("iffi"), .string("lab")]),
        ])
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
