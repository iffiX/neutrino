import SwiftUI

/// The top bar: the page title at the left, after a back arrow on a page reached from another, and the refresh
/// button at the right. Its background and its bottom rule run to the screen's edges.
struct TopBar: View {
    /// The page's title.
    let title: String

    /// What the back arrow does; nil for a bar page, which has none.
    let onBack: (() -> Void)?

    /// Whether any hub refreshes, which turns the button into a spinner.
    let isRefreshing: Bool

    /// What the refresh button does.
    let onRefresh: () -> Void

    @Environment(\.words) private var words
    @Environment(\.palette) private var palette

    var body: some View {
        HStack(spacing: 12) {
            if let onBack {
                Button(action: onBack) {
                    Image(systemName: "chevron.left").font(.system(size: 17, weight: .semibold))
                }
                .accessibilityLabel(words.word("ui.back"))
                .foregroundColor(palette.text)
            }
            Text(title).font(.system(size: 18, weight: .semibold)).foregroundColor(palette.text).lineLimit(1)
            Spacer()
            Button(action: onRefresh) {
                if isRefreshing {
                    ProgressView().controlSize(.small).tint(palette.signalWarn)
                } else {
                    Image(systemName: "arrow.clockwise").font(.system(size: 16, weight: .medium))
                }
            }
            .disabled(isRefreshing)
            .accessibilityLabel(words.word("ui.refresh"))
            .foregroundColor(palette.text)
        }
        .padding(.horizontal, 16)
        .frame(height: Client.headerHeight)
        .background {
            VStack(spacing: 0) {
                palette.surface
                palette.border.frame(height: 1)
            }
            .ignoresSafeArea(edges: [.top, .horizontal])
        }
    }
}
