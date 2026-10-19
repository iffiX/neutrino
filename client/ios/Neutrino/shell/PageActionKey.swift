import SwiftUI

/// The page action the shown page offers, read by the shell.
struct PageActionKey: PreferenceKey {
    static let defaultValue: PageAction? = nil

    static func reduce(value: inout PageAction?, nextValue: () -> PageAction?) {
        value = nextValue() ?? value
    }
}
