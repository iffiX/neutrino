import Foundation

/// One of the three round buttons at the viewer's top right.
enum RemoteDesktopButton: String, CaseIterable, Identifiable {
    case keyboard
    case keys
    case close

    /// The button's name, as a list keys it.
    var id: String { rawValue }

    /// The catalog key of its label.
    var wordKey: String {
        switch self {
        case .keyboard: return "ui.rdp_keyboard"
        case .keys: return "ui.rdp_keys"
        case .close: return "ui.rdp_disconnect"
        }
    }

    /// The SF Symbol it shows.
    var systemImage: String {
        switch self {
        case .keyboard: return "keyboard"
        case .keys: return "command"
        case .close: return "xmark"
        }
    }

    /// Whether it is drawn in the danger tone.
    var isDanger: Bool { self == .close }

    /// Whether the button shows as active.
    ///
    /// - Parameters:
    ///   - keyboard: The phone's keyboard.
    ///   - isKeyBarShown: Whether the key bar shows.
    /// - Returns: True for Keyboard while the system shows the keyboard, floating or not, and for Keys while the
    ///   key bar shows.
    func isActive(keyboard: RemoteDesktopKeyboard, isKeyBarShown: Bool) -> Bool {
        switch self {
        case .keyboard: return keyboard.isShown
        case .keys: return isKeyBarShown
        case .close: return false
        }
    }

    /// What a press does: Keyboard raises or puts away the keyboard, Keys shows or hides the key bar, Close ends
    /// the session.
    ///
    /// - Parameters:
    ///   - keyboard: The phone's keyboard.
    ///   - isKeyBarShown: Whether the key bar shows.
    ///   - onKeyboard: Called with whether the keyboard is to be up.
    ///   - onKeyBar: Called with whether the key bar is to show.
    ///   - onClose: Called to end the session.
    func press(
        keyboard: RemoteDesktopKeyboard, isKeyBarShown: Bool, onKeyboard: (Bool) -> Void, onKeyBar: (Bool) -> Void,
        onClose: () -> Void
    ) {
        switch self {
        case .keyboard: onKeyboard(!isActive(keyboard: keyboard, isKeyBarShown: isKeyBarShown))
        case .keys: onKeyBar(!isKeyBarShown)
        case .close: onClose()
        }
    }
}
