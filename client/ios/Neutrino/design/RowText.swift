import SwiftUI

/// One line of a row, in one of the row's styles.
struct RowText: View {
    /// The line's style.
    enum Style {
        /// The row's title.
        case title
        /// A sentence of the body.
        case body
        /// The state line, muted.
        case note
        /// An address, a path: monospaced and muted.
        case mono
        /// The code of the row's last action, in the error colour.
        case error
        /// Why a button is disabled, faint.
        case reason
    }

    /// The text.
    let text: String

    /// The style.
    var style = Style.body

    @Environment(\.palette) private var palette

    var body: some View {
        Text(text).font(font).foregroundColor(color).fixedSize(horizontal: false, vertical: true)
    }

    private var font: Font {
        switch style {
        case .title: return .system(size: 15, weight: .semibold)
        case .body: return .system(size: 14)
        case .note, .error, .reason: return .system(size: 12)
        case .mono: return .system(size: 12, design: .monospaced)
        }
    }

    private var color: Color {
        switch style {
        case .title, .body: return palette.text
        case .note, .mono: return palette.textMuted
        case .error: return palette.error
        case .reason: return palette.textFaint
        }
    }
}
