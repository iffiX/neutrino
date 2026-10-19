import SwiftUI

/// A card: one concern of a page, on the surface colour with the plain border.
struct SurfaceCard<Content: View>: View {
    private let content: Content

    @Environment(\.palette) private var palette

    /// Put content in a card.
    ///
    /// - Parameter content: The card's rows.
    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) { content }
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 12).fill(palette.surface))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(palette.border, lineWidth: 1))
    }
}
