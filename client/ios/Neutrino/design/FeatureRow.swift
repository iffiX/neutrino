import SwiftUI

/// A row, the unit every page is made of: the status dot at the left, the body's lines, and the row's actions
/// at the right, or wrapped under the body, right-aligned, where the row is too narrow.
struct FeatureRow<Lines: View, Actions: View>: View {
    private let marker: DotTone?
    private let hasDivider: Bool
    private let lines: Lines
    private let actions: Actions

    @Environment(\.palette) private var palette

    /// Lay out a row.
    ///
    /// - Parameters:
    ///   - marker: The status dot's tone, nil for no dot.
    ///   - hasDivider: Whether a rule parts it from the row under it.
    ///   - lines: The body's lines.
    ///   - actions: The row's actions, in one line.
    init(
        marker: DotTone? = nil, hasDivider: Bool = false, @ViewBuilder lines: () -> Lines,
        @ViewBuilder actions: () -> Actions
    ) {
        self.marker = marker
        self.hasDivider = hasDivider
        self.lines = lines()
        self.actions = actions()
    }

    var body: some View {
        VStack(spacing: 0) {
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .top, spacing: 12) {
                    head
                    HStack(spacing: 8) { actions }.fixedSize()
                }
                VStack(alignment: .trailing, spacing: 8) {
                    head
                    HStack(spacing: 8) { actions }
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
        }
    }
}
