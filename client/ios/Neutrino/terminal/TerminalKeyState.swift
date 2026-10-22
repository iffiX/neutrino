import Combine

/// The key row, one for every tab: whether it shows, and the modifiers held for the next key. A press on a
/// modifier holds it or lets it go, and the next key, from the row or the keyboard, spends them all.
final class TerminalKeyState: ObservableObject {
    /// The modifiers held.
    @Published private(set) var modifiers = TerminalModifiers()

    /// Whether the key row shows; it starts shown.
    @Published private(set) var isRowShown = true

    /// The status line's Keys: the key row hides or shows again.
    func toggleRow() {
        isRowShown.toggle()
    }

    /// A press on a modifier of the row.
    ///
    /// - Parameter key: The modifier.
    func toggle(_ key: TerminalKey) {
        modifiers = modifiers.toggled(key)
    }

    /// Spend the held modifiers on a key.
    ///
    /// - Returns: The modifiers that were held.
    func spend() -> TerminalModifiers {
        let held = modifiers
        if held.isAny { modifiers = TerminalModifiers() }
        return held
    }
}
