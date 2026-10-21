import Foundation

/// A key of the viewer's key bar, by the name RustDesk gives it.
enum RemoteDesktopKey: String, CaseIterable, Identifiable {
    case escape = "VK_ESCAPE"
    case tab = "VK_TAB"
    case ctrl = "VK_CONTROL"
    case shift = "VK_SHIFT"
    case alt = "VK_MENU"
    case win = "VK_LWIN"
    case left = "VK_LEFT"
    case up = "VK_UP"
    case down = "VK_DOWN"
    case right = "VK_RIGHT"

    /// RustDesk's name for Enter.
    static let enter = "VK_RETURN"

    /// RustDesk's name for Backspace.
    static let backspace = "VK_BACK"

    /// RustDesk's name for Delete.
    static let delete = "VK_DELETE"

    /// RustDesk's name for the V that Ctrl turns into a paste.
    static let paste = "VK_V"

    /// RustDesk's name for the Insert that Shift turns into a paste.
    static let insert = "VK_INSERT"

    /// RustDesk's name for the key.
    var code: String { rawValue }

    /// The key's name, as a list keys it.
    var id: String { rawValue }

    /// What the bar shows.
    var label: String {
        switch self {
        case .escape: return "Esc"
        case .tab: return "Tab"
        case .ctrl: return "Ctrl"
        case .shift: return "Shift"
        case .alt: return "Alt"
        case .win: return "Win"
        case .left: return "←"
        case .up: return "↑"
        case .down: return "↓"
        case .right: return "→"
        }
    }

    /// Whether a press holds it for the next key rather than typing it.
    var isModifier: Bool {
        switch self {
        case .ctrl, .shift, .alt, .win: return true
        default: return false
        }
    }

    /// RustDesk's name for a typed character that a held modifier applies to: a letter or a digit.
    ///
    /// - Parameter character: The character.
    /// - Returns: The key's name, or nil for any other character.
    static func code(of character: Character) -> String? {
        let upper = character.uppercased()
        guard upper.unicodeScalars.count == 1, let scalar = upper.unicodeScalars.first else { return nil }
        let isLetter = (0x41...0x5A).contains(scalar.value)
        let isDigit = (0x30...0x39).contains(scalar.value)
        return isLetter || isDigit ? "VK_\(upper)" : nil
    }
}
