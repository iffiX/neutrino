import Foundation

/// A key of the row above the keyboard, in the row's order.
enum TerminalKey: CaseIterable {
    case escape
    case tab
    case ctrl
    case shift
    case alt
    case left
    case up
    case down
    case right

    /// What the row shows.
    var label: String {
        switch self {
        case .escape: return "Esc"
        case .tab: return "Tab"
        case .ctrl: return "Ctrl"
        case .shift: return "Shift"
        case .alt: return "Alt"
        case .left: return "←"
        case .up: return "↑"
        case .down: return "↓"
        case .right: return "→"
        }
    }

    /// Whether a press holds it for the next key rather than sending it.
    var isModifier: Bool { self == .ctrl || self == .shift || self == .alt }

    /// What the key sends to the shell with the held modifiers, as xterm encodes it: Alt puts Escape before Esc
    /// and Tab, Shift turns Tab into back-tab, and an arrow carries every modifier in its parameter, or reads as
    /// the application's cursor keys when the terminal asked for them and nothing is held.
    ///
    /// - Parameters:
    ///   - modifiers: The modifiers held.
    ///   - isApplicationCursor: Whether the terminal is in application cursor mode.
    /// - Returns: The bytes; empty for a modifier.
    func sequence(_ modifiers: TerminalModifiers, isApplicationCursor: Bool = false) -> Data {
        let escape = TerminalPage.escape
        let alt: [UInt8] = modifiers.isAlt ? [escape] : []
        switch self {
        case .escape: return Data(alt + [escape])
        case .tab: return Data(alt + (modifiers.isShift ? [escape, 0x5b, 0x5a] : [0x09]))
        case .left: return arrow(0x44, modifiers, isApplicationCursor)
        case .up: return arrow(0x41, modifiers, isApplicationCursor)
        case .down: return arrow(0x42, modifiers, isApplicationCursor)
        case .right: return arrow(0x43, modifiers, isApplicationCursor)
        case .ctrl, .shift, .alt: return Data()
        }
    }

    private func arrow(_ letter: UInt8, _ modifiers: TerminalModifiers, _ isApplicationCursor: Bool) -> Data {
        let parameter = modifiers.xtermParameter
        if parameter == 1 {
            return Data([TerminalPage.escape, isApplicationCursor ? 0x4f : 0x5b, letter])
        }
        return Data([TerminalPage.escape, 0x5b, 0x31, 0x3b] + Array("\(parameter)".utf8) + [letter])
    }
}
