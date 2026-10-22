import SwiftUI
import UIKit

/// A clear layer behind a page's content: one tap on it, where no control or field is in front, closes the
/// keyboard.
struct KeyboardClosingLayer: View {
    var body: some View {
        Color.clear
            .contentShape(Rectangle())
            .onTapGesture { Self.close() }
    }

    /// Close the keyboard, whatever has the typing.
    static func close() {
        UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
    }
}
