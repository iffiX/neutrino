import SwiftUI

/// The frame of every page: the sidebar when the window is wider than it is tall or at least 720 points wide,
/// the bottom bar otherwise; the top bar above the page; and the page's own action at the right of the page
/// header beside the sidebar, or as a floating button above the bottom bar.
struct AppShell: View {
    @ObservedObject var core: ClientCore

    /// The views of every terminal tab.
    let cache: TerminalViewCache

    @Environment(\.words) private var words
    @Environment(\.palette) private var palette
    @State private var screen = AppScreen.hubs
    @State private var pageAction: PageAction?

    var body: some View {
        GeometryReader { window in
            let isSidebar = window.size.width > window.size.height || window.size.width >= Client.sidebarMinWidth
            if isSidebar {
                HStack(spacing: 0) {
                    PageBar(isSidebar: true, selected: selection)
                    main(isSidebar: true)
                }
            } else {
                VStack(spacing: 0) {
                    main(isSidebar: false)
                    PageBar(isSidebar: false, selected: selection)
                }
            }
        }
        .background(palette.bg.ignoresSafeArea())
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

    private func main(isSidebar: Bool) -> some View {
        VStack(spacing: 0) {
            TopBar(title: title, onBack: onBack, isRefreshing: core.isRefreshing) { core.refresh() }
            if isSidebar, core.browser == nil, let action = pageAction {
                HStack {
                    Spacer()
                    NeutrinoButton(
                        label: action.label, tier: .primary, isEnabled: action.isEnabled, action: action.action)
                }
                .padding(.horizontal, 16)
                .padding(.top, 12)
            }
            page
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .overlay(alignment: .bottomTrailing) {
                    if !isSidebar, core.browser == nil, let action = pageAction {
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
            case .files: FilesScreen(core: core)
            case .terminals: TerminalScreen(core: core, cache: cache)
            case .settings: SettingsScreen(core: core)
            case .join: JoinScreen(core: core) { screen = .hubs }
            }
        }
    }

    private var title: String {
        if let browser = core.browser { return browser.title }
        return words.word(screen.titleKey)
    }

    private var onBack: (() -> Void)? {
        if core.browser != nil { return { core.browser = nil } }
        guard let parent = screen.parent else { return nil }
        return { screen = parent }
    }

    private func floatingButton(_ action: PageAction) -> some View {
        Button(action: action.action) {
            Image(systemName: action.systemImage)
                .font(.system(size: 20, weight: .semibold))
                .foregroundColor(action.isEnabled ? palette.bg : palette.textFaint)
                .frame(width: 56, height: 56)
                .background(Circle().fill(action.isEnabled ? palette.accent : palette.elevated))
        }
        .buttonStyle(.plain)
        .disabled(!action.isEnabled)
        .accessibilityLabel(action.label)
        .padding(16)
    }
}
