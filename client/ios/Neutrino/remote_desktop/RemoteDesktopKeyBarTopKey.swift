import SwiftUI

/// The viewer's key bar's top edge in the window, read by the viewer; nil while the key bar is hidden.
struct RemoteDesktopKeyBarTopKey: PreferenceKey {
    static let defaultValue: Double? = nil

    static func reduce(value: inout Double?, nextValue: () -> Double?) {
        value = nextValue() ?? value
    }
}
