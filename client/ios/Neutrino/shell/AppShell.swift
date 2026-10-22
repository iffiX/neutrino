import SwiftUI

/// The frame of every page: the sidebar when the window is wider than it is tall or at least 720 points wide,
/// the bottom bar otherwise; the top bar above the page; and the page's own action at the right of the page
/// header beside the sidebar. Above the bottom bar a page draws its action itself, and the share page's actions
/// are the one floating button in both layouts. With the keyboard shown the bottom bar stays under it, and the
/// page ends at the keyboard, following its slide frame by frame. In landscape the sidebar keeps the safe area only
/// on the camera housing's side.
/// The Files page shows the share page while a share is open, and the remote desktop viewer covers the whole
/// screen while it is open.
struct AppShell: View {
    @ObservedObject var core: ClientCore

    /// The views of every terminal tab.
    let cache: TerminalViewCache

    @Environment(\.words) private var words
    @Environment(\.palette) private var palette
    @State private var screen = AppScreen.hubs
    @State private var pageAction: PageAction?
    @StateObject private var orientation = ShellOrientation()
    @ObservedObject private var keyboard: KeyboardMotion

    /// Draw the frame.
    ///
    /// - Parameters:
    ///   - core: The app core.
    ///   - cache: The views of every terminal tab.
    ///   - screen: The page shown first.
    init(core: ClientCore, cache: TerminalViewCache, screen: AppScreen = .hubs) {
        _core = ObservedObject(wrappedValue: core)
        self.cache = cache
        _screen = State(initialValue: screen)
        _keyboard = ObservedObject(wrappedValue: cache.keyboard)
    }

    var body: some View {
        GeometryReader { window in
            let isSidebar = window.size.width > window.size.height || window.size.width >= Client.sidebarMinWidth
            if isSidebar {
                let isHousingRight = ShellOrientation.isHousingRight(orientation.orientation)
                let isInset = window.safeAreaInsets.leading > 0 && !isHousingRight
                HStack(spacing: 0) {
                    PageBar(isSidebar: true, isInset: isInset, selected: selection)
                    main(isSidebar: true).padding(.bottom, keyboard.overlap)
                }
                .ignoresSafeArea(.container, edges: isHousingRight ? .leading : [])
                .environment(\.isSidebar, true)
            } else {
                let isBarCovered = keyboard.overlap >= Client.barHeight
                let below = isBarCovered ? keyboard.overlap : max(0, keyboard.overlap - Client.barHeight)
                VStack(spacing: 0) {
                    main(isSidebar: false).padding(.bottom, below)
                    if !isBarCovered {
                        PageBar(isSidebar: false, selected: selection)
                    }
                }
                .environment(\.isSidebar, false)
            }
        }
        .ignoresSafeArea(.keyboard)
        .background(palette.bg.ignoresSafeArea())
        .onAppear { orientation.follow() }
        .fullScreenCover(item: viewing) { target in
            RemoteDesktopViewer(target: target, core: core.remoteDesktop) { core.closeDesktop() }
                .environment(\.words, words)
                .environment(\.palette, palette)
        }
        .onOpenURL { url in
            core.browser = nil
            screen = .join
            core.join(url.absoluteString)
        }
    }

    private var selection: Binding<AppScreen> {
        Binding(
            get: { screen },
            set: { next in
                core.browser = nil
                screen = next
            })
    }

    private var viewing: Binding<RemoteDesktopTarget?> {
        Binding(
            get: { core.viewing },
            set: { next in
                if next == nil { core.closeDesktop() }
            })
    }

    private func main(isSidebar: Bool) -> some View {
        VStack(spacing: 0) {
            TopBar(
                title: title, onBack: onBack, isRefreshing: core.isRefreshing,
                action: isSidebar && core.browser == nil && pageAction?.items.isEmpty == true ? pageAction : nil
            ) { core.refresh() }
            page
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .overlay(alignment: .bottomTrailing) {
                    if core.browser == nil, let action = pageAction, !isSidebar || !action.items.isEmpty {
                        floatingButton(action)
                    }
                }
        }
        .onPreferenceChange(PageActionKey.self) { pageAction = $0 }
    }

    @ViewBuilder private var page: some View {
        if let browser = core.browser {
            BrowserWebView(target: browser).id(browser.url)
        } else {
            switch screen {
            case .hubs: HubsScreen(core: core) { screen = .join }
            case .web: WebScreen(core: core)
            case .files:
                if let share = core.share {
                    ShareScreen(core: core, share: share)
                } else {
                    FilesScreen(core: core)
                }
            case .terminals: TerminalScreen(core: core, cache: cache)
            case .desktops: RemoteDesktopScreen(core: core)
            case .settings: SettingsScreen(core: core)
            case .join: JoinScreen(core: core) { screen = .hubs }
            }
        }
    }

    private var title: String {
        if let browser = core.browser { return browser.title }
        if screen == .files, let share = core.share {
            return share.path.parts.isEmpty ? share.target.title : share.path.name
        }
        return words.word(screen.titleKey)
    }

    private var onBack: (() -> Void)? {
        if core.browser != nil { return { core.browser = nil } }
        if screen == .files, core.share != nil { return { core.shares.back() } }
        guard let parent = screen.parent else { return nil }
        return { screen = parent }
    }

    @ViewBuilder
    private func floatingButton(_ action: PageAction) -> some View {
        if action.items.isEmpty {
            Button(action: action.action) { floatingCircle(action) }
                .buttonStyle(.plain)
                .disabled(!action.isEnabled)
                .accessibilityLabel(action.label)
                .padding(16)
        } else {
            Menu {
                ForEach(Array(action.items.enumerated()), id: \.offset) { _, item in
                    Button(action: item.action) { Label(item.label, systemImage: item.systemImage) }
                        .disabled(!item.isEnabled)
                }
            } label: {
                floatingCircle(action)
            }
            .disabled(!action.isEnabled)
            .accessibilityLabel(action.label)
            .padding(16)
        }
    }

    private func floatingCircle(_ action: PageAction) -> some View {
        Image(systemName: action.systemImage)
            .font(.system(size: 20, weight: .semibold))
            .foregroundColor(action.isEnabled ? palette.bg : palette.textFaint)
            .frame(width: 56, height: 56)
            .background(Circle().fill(action.isEnabled ? palette.accent : palette.elevated))
    }
}
