import SwiftUI

/// A row, the unit every page is made of: the status dot at the left, the body's lines, a chevron at the right for
/// a row that opens something, and under them the row's actions, right-aligned, wrapping to another line where one
/// is too narrow.
struct FeatureRow<Lines: View, Actions: View>: View {
    private let marker: DotTone?
    private let hasDivider: Bool
    private let hasChevron: Bool
    private let lines: Lines
    private let actions: Actions

    @Environment(\.palette) private var palette

    /// Lay out a row.
    ///
    /// - Parameters:
    ///   - marker: The status dot's tone, nil for no dot.
    ///   - hasDivider: Whether a rule parts it from the row under it.
    ///   - hasChevron: Whether a chevron ends the row, for a row that opens something.
    ///   - lines: The body's lines.
    ///   - actions: The row's actions, in their order.
    init(
        marker: DotTone? = nil, hasDivider: Bool = false, hasChevron: Bool = false, @ViewBuilder lines: () -> Lines,
        @ViewBuilder actions: () -> Actions
    ) {
        self.marker = marker
        self.hasDivider = hasDivider
        self.hasChevron = hasChevron
        self.lines = lines()
        self.actions = actions()
    }

    var body: some View {
        VStack(spacing: 0) {
            VStack(alignment: .trailing, spacing: 8) {
                head
                if Actions.self != EmptyView.self {
                    FlowRow(isTrailing: true) { actions }
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            if hasDivider {
                Rectangle().fill(palette.border).frame(height: 1)
            }
        }
    }

    private var head: some View {
        HStack(alignment: .top, spacing: 10) {
            if let marker {
                StatusDot(tone: marker).padding(.top, 6)
            }
            VStack(alignment: .leading, spacing: 3) { lines }
                .frame(maxWidth: .infinity, alignment: .leading)
            if hasChevron {
                Image(systemName: "chevron.right").foregroundColor(palette.textFaint).padding(.top, 3)
            }
        }
    }
}
