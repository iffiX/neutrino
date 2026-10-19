import Foundation

/// The key row's modifiers held for the next key: a press on one holds it or lets it go, and the next key, from
/// the row or the keyboard, spends them all.
struct TerminalModifiers: Equatable {
    /// Whether Ctrl is held.
    var isCtrl = false

    /// Whether Shift is held.
    var isShift = false

    /// Whether Alt is held.
    var isAlt = false

    /// Whether any modifier is held.
    var isAny: Bool { isCtrl || isShift || isAlt }

    /// xterm's modifier parameter: 1, plus 1 for Shift, 2 for Alt and 4 for Ctrl.
    var xtermParameter: Int { 1 + (isShift ? 1 : 0) + (isAlt ? 2 : 0) + (isCtrl ? 4 : 0) }

    /// Whether one key of the row shows pressed.
    ///
    /// - Parameter key: The key.
    /// - Returns: True for a modifier that is held.
    func isHeld(_ key: TerminalKey) -> Bool {
        switch key {
        case .ctrl: return isCtrl
        case .shift: return isShift
        case .alt: return isAlt
        default: return false
        }
    }

    /// The modifiers after a press on one key of the row.
    ///
    /// - Parameter key: The key; a key that is no modifier changes nothing.
    /// - Returns: The modifiers with that one held or let go.
    func toggled(_ key: TerminalKey) -> TerminalModifiers {
        var next = self
        switch key {
        case .ctrl: next.isCtrl.toggle()
        case .shift: next.isShift.toggle()
        case .alt: next.isAlt.toggle()
        default: break
        }
        return next
    }

    /// What one key typed on the keyboard sends with the held modifiers: Shift makes a letter capital, Ctrl turns
    /// a letter or `@[\]^_` into its control byte, and Alt puts Escape before it. Anything longer than one byte
    /// goes as it is.
    ///
    /// - Parameter bytes: What the keyboard sent.
    /// - Returns: The bytes to send.
    func applied(to bytes: Data) -> Data {
        guard bytes.count == 1, var byte = bytes.first else { return bytes }
        if isShift, (0x61...0x7a).contains(byte) { byte -= 0x20 }
        if isCtrl {
            if (0x61...0x7a).contains(byte) {
                byte -= 0x60
            } else if (0x40...0x5f).contains(byte) {
                byte -= 0x40
            } else if byte == 0x20 {
                byte = 0
            }
        }
        return isAlt ? Data([TerminalPage.escape, byte]) : Data([byte])
    }
}
