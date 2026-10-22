import Combine

/// The key row's modifiers held for the next key, one set for every tab: a press on a modifier holds it or lets it
/// go, and the next key, from the row or the keyboard, spends them all.
final class TerminalKeyState: ObservableObject {
    /// The modifiers held.
    @Published private(set) var modifiers = TerminalModifiers()

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
