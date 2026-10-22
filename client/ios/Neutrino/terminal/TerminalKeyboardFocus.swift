import Combine
import UIKit

/// What a tap on a terminal does to the keyboard: it opens it, and brings it back when iOS took it away while the
/// terminal kept the focus, by taking the focus again. The phone's keyboard is followed through its notifications,
/// for the status line's Keyboard button too.
final class TerminalKeyboardFocus: NSObject, ObservableObject, UIGestureRecognizerDelegate {
    /// Whether the system shows the keyboard.
    @Published private(set) var isKeyboardShown = false

    private var isRefocusing = false

    override init() {
        super.init()
        let center = NotificationCenter.default
        center.addObserver(
            self, selector: #selector(keyboardWillShow), name: UIResponder.keyboardWillShowNotification, object: nil)
        center.addObserver(
            self, selector: #selector(keyboardWillHide), name: UIResponder.keyboardWillHideNotification, object: nil)
    }

    /// Watch the taps on one terminal view.
    ///
    /// - Parameter view: The view.
    func watch(_ view: UIView) {
        let tap = UITapGestureRecognizer(target: self, action: #selector(tapped(_:)))
        tap.cancelsTouchesInView = false
        tap.delegate = self
        view.addGestureRecognizer(tap)
    }

    /// Whether a tap must take the focus again for the keyboard to show.
    ///
    /// - Parameters:
    ///   - isFocused: Whether the terminal has the focus when the tap starts.
    ///   - isKeyboardShown: Whether the system shows the keyboard then.
    /// - Returns: True when the terminal has the focus and no keyboard shows.
    static func needsRefocus(isFocused: Bool, isKeyboardShown: Bool) -> Bool {
        isFocused && !isKeyboardShown
    }

    func gestureRecognizer(_ gestureRecognizer: UIGestureRecognizer, shouldReceive touch: UITouch) -> Bool {
        let isFocused = gestureRecognizer.view?.isFirstResponder ?? false
        isRefocusing = Self.needsRefocus(isFocused: isFocused, isKeyboardShown: isKeyboardShown)
        return true
    }

    func gestureRecognizer(
        _ gestureRecognizer: UIGestureRecognizer,
        shouldRecognizeSimultaneouslyWith otherGestureRecognizer: UIGestureRecognizer
    ) -> Bool {
        true
    }

    @objc private func keyboardWillShow() {
        isKeyboardShown = true
    }

    @objc private func keyboardWillHide() {
        isKeyboardShown = false
    }

    @objc private func tapped(_ tap: UITapGestureRecognizer) {
        guard tap.state == .ended, isRefocusing, let view = tap.view else { return }
        isRefocusing = false
        _ = view.resignFirstResponder()
        _ = view.becomeFirstResponder()
    }
}
