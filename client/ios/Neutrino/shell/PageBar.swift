import SwiftUI

/// The bar of pages: the bottom bar in portrait on a phone, the sidebar otherwise; it carries only the pages.
struct PageBar: View {
    /// Whether it is drawn as the sidebar.
    let isSidebar: Bool

    /// The page shown.
    @Binding var selected: AppScreen

    @Environment(\.words) private var words
    @Environment(\.palette) private var palette

    var body: some View {
        if isSidebar {
            VStack(alignment: .leading, spacing: 4) {
                ForEach(AppScreen.tabs) { screen in
                    entry(screen, isWide: true)
                }
                Spacer()
            }
            .padding(8)
            .frame(width: 200)
            .background(palette.surface)
            .overlay(Rectangle().fill(palette.border).frame(width: 1), alignment: .trailing)
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
                        Text(words.word(screen.titleKey)).font(.system(size: 10, weight: .medium)).lineLimit(1)
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
