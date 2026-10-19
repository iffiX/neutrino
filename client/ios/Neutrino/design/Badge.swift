import SwiftUI

/// A short tag beside a title: a way in, a round trip, `kept`, `shared`, a count.
struct Badge: View {
    /// The tag.
    let text: String

    @Environment(\.palette) private var palette

    var body: some View {
        Text(text)
            .font(.system(size: 11, weight: .medium))
            .foregroundColor(palette.textMuted)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(RoundedRectangle(cornerRadius: 4).fill(palette.elevated))
            .overlay(RoundedRectangle(cornerRadius: 4).stroke(palette.border, lineWidth: 1))
            .lineLimit(1)
    }
}
