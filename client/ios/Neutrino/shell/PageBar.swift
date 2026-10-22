import SwiftUI

/// The bar of pages: the bottom bar in portrait on a phone, the sidebar otherwise. The sidebar has the client's
/// name in a box at its top, as tall as the page header beside it, then each page by its full name with Settings
/// apart under a rule; the bottom bar names Remote desktops Desktops. The sidebar's background and divider run to
/// the screen's edges; its entries start at the safe area's edge, with no space added where the screen's edge
/// insets it.
struct PageBar: View {
    /// Whether it is drawn as the sidebar.
    let isSidebar: Bool

    /// Whether the screen's edge beside the sidebar insets it, as a camera housing does in landscape.
    var isInset = false

    /// The page shown.
    @Binding var selected: AppScreen

    @Environment(\.words) private var words
    @Environment(\.palette) private var palette

    var body: some View {
        if isSidebar {
            let leading = isInset ? 0.0 : 8.0
            VStack(alignment: .leading, spacing: 0) {
                Text(words.word("ui.window.title"))
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundColor(palette.text)
                    .lineLimit(1)
                    .padding(.leading, leading + 12)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
                    .frame(height: Client.headerHeight)
                    .background(alignment: .bottom) {
                        palette.border.frame(height: 1).ignoresSafeArea(edges: .horizontal)
                    }
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(AppScreen.tabs) { screen in
                        if screen == .settings {
                            palette.border.frame(height: 1).padding(.vertical, 12)
                        }
                        entry(screen, isWide: true)
                    }
                    Spacer()
                }
                .padding(.vertical, 8)
                .padding(.leading, leading)
                .padding(.trailing, 8)
            }
            .frame(width: Client.sidebarWidth)
            .background {
                HStack(spacing: 0) {
                    palette.surface
                    palette.border.frame(width: 1)
                }
                .ignoresSafeArea()
            }
        } else {
            HStack(spacing: 0) {
                ForEach(AppScreen.tabs) { screen in
                    entry(screen, isWide: false).frame(maxWidth: .infinity)
                }
            }
            .frame(height: 56)
            .background(palette.surface)
            .overlay(Rectangle().fill(palette.border).frame(height: 1), alignment: .top)
        }
    }

    private func entry(_ screen: AppScreen, isWide: Bool) -> some View {
        let isOn = (selected.parent ?? selected) == screen
        return Button {
            selected = screen
        } label: {
            Group {
                if isWide {
                    HStack(spacing: 10) {
                        Image(systemName: screen.systemImage).frame(width: 22)
                        Text(words.word(screen.titleKey)).font(.system(size: 14, weight: .medium))
                        Spacer()
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 9)
                } else {
                    VStack(spacing: 3) {
                        Image(systemName: screen.systemImage).font(.system(size: 18))
                        Text(words.word(screen.barKey)).font(.system(size: 10, weight: .medium)).lineLimit(1)
                    }
                }
            }
            .foregroundColor(isOn ? palette.accent : palette.textMuted)
            .background(RoundedRectangle(cornerRadius: 8).fill(isOn && isWide ? palette.accentWash : .clear))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}
