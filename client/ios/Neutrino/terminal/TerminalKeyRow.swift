import UIKit

/// The row above the keyboard: Esc, Tab, Ctrl, Shift, Alt and the four arrows; a modifier is sticky for one key
/// and shows pressed while held.
final class TerminalKeyRow: UIInputView {
    /// Called with a key that is no modifier, and the modifiers held when it was pressed.
    var onKey: ((TerminalKey, TerminalModifiers) -> Void)?

    /// The modifiers held for the next key.
    private(set) var modifiers = TerminalModifiers() {
        didSet { paint() }
    }

    private var buttons: [TerminalKey: UIButton] = [:]
    private let accent: UIColor

    /// Make the row.
    ///
    /// - Parameter accent: The colour a held modifier is drawn in.
    init(accent: UIColor) {
        self.accent = accent
        super.init(frame: CGRect(x: 0, y: 0, width: 320, height: 44), inputViewStyle: .keyboard)
        let stack = UIStackView()
        stack.axis = .horizontal
        stack.distribution = .fillEqually
        stack.spacing = 4
        stack.translatesAutoresizingMaskIntoConstraints = false
        for key in TerminalKey.allCases {
            let button = UIButton(type: .system)
            button.setTitle(key.label, for: .normal)
            button.titleLabel?.font = .systemFont(ofSize: 14, weight: .medium)
            button.layer.cornerRadius = 6
            button.backgroundColor = .secondarySystemBackground
            button.addAction(UIAction { [weak self] _ in self?.press(key) }, for: .touchUpInside)
            buttons[key] = button
            stack.addArrangedSubview(button)
        }
        addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 4),
            stack.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -4),
            stack.topAnchor.constraint(equalTo: topAnchor, constant: 4),
            stack.bottomAnchor.constraint(equalTo: bottomAnchor, constant: -4),
        ])
        autoresizingMask = .flexibleWidth
        paint()
    }

    required init?(coder: NSCoder) {
        return nil
    }

    /// Spend the held modifiers on a key typed on the keyboard.
    ///
    /// - Returns: The modifiers that were held.
    func spend() -> TerminalModifiers {
        let held = modifiers
        if held.isAny { modifiers = TerminalModifiers() }
        return held
    }

    private func press(_ key: TerminalKey) {
        if key.isModifier {
            modifiers = modifiers.toggled(key)
            return
        }
        onKey?(key, spend())
    }

    private func paint() {
        for (key, button) in buttons {
            let isHeld = modifiers.isHeld(key)
            button.tintColor = isHeld ? accent : .label
            button.layer.borderWidth = isHeld ? 1 : 0
            button.layer.borderColor = accent.cgColor
        }
    }
}
