import UIKit

/// The invisible view the phone's keyboard types into while the viewer takes typing: a text input whose only text
/// is what the keyboard marks, handed with every commit and delete to its connection. No autocorrection, no
/// capitals and no smart punctuation. Escape and the arrows of a hardware keyboard are sent as their keys.
final class RemoteDesktopInputView: UIView, UITextInput {
    /// Where the keyboard's text and deletes go; the keyboard types into nothing while it is nil.
    var connection: RemoteDesktopInputConnection?

    /// The input's traits.
    var autocorrectionType = UITextAutocorrectionType.no
    var autocapitalizationType = UITextAutocapitalizationType.none
    var spellCheckingType = UITextSpellCheckingType.no
    var smartQuotesType = UITextSmartQuotesType.no
    var smartDashesType = UITextSmartDashesType.no
    var smartInsertDeleteType = UITextSmartInsertDeleteType.no
    var keyboardType = UIKeyboardType.default
    var returnKeyType = UIReturnKeyType.default

    /// What the keyboard tells of its own changes.
    weak var inputDelegate: UITextInputDelegate?

    /// How marked text is drawn; this view draws none.
    var markedTextStyle: [NSAttributedString.Key: Any]?

    private lazy var stringTokenizer = UITextInputStringTokenizer(textInput: self)

    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundColor = .clear
        isUserInteractionEnabled = false
    }

    required init?(coder: NSCoder) {
        return nil
    }

    override var canBecomeFirstResponder: Bool { true }

    override func pressesBegan(_ presses: Set<UIPress>, with event: UIPressesEvent?) {
        for press in presses {
            if let code = press.key.flatMap({ Self.keyCode($0.keyCode) }) { connection?.press(code) }
        }
        super.pressesBegan(presses, with: event)
    }

    // MARK: The keyboard's text

    var hasText: Bool { true }

    func insertText(_ text: String) {
        connection?.insert(text)
    }

    func deleteBackward() {
        connection?.deleteBackward()
    }

    func setMarkedText(_ markedText: String?, selectedRange: NSRange) {
        connection?.setMarked(markedText ?? "", selection: selectedRange)
    }

    func unmarkText() {
        connection?.unmark()
    }

    func text(in range: UITextRange) -> String? {
        guard let range = range as? RemoteDesktopTextRange else { return nil }
        let marked = (connection?.marked ?? "") as NSString
        let window = NSIntersectionRange(range.nsRange, NSRange(location: 0, length: marked.length))
        return marked.substring(with: window)
    }

    func replace(_ range: UITextRange, withText text: String) {
        connection?.insert(text)
    }

    var selectedTextRange: UITextRange? {
        get {
            let selection = connection?.selection ?? NSRange(location: 0, length: 0)
            return RemoteDesktopTextRange(selection.location, selection.location + selection.length)
        }
        set {}
    }

    var markedTextRange: UITextRange? {
        let length = ((connection?.marked ?? "") as NSString).length
        return length == 0 ? nil : RemoteDesktopTextRange(0, length)
    }

    // MARK: Positions in the marked text

    var beginningOfDocument: UITextPosition { RemoteDesktopTextPosition(0) }

    var endOfDocument: UITextPosition { RemoteDesktopTextPosition(documentLength) }

    var tokenizer: UITextInputTokenizer { stringTokenizer }

    func textRange(from fromPosition: UITextPosition, to toPosition: UITextPosition) -> UITextRange? {
        RemoteDesktopTextRange(offset(of: fromPosition), offset(of: toPosition))
    }

    func position(from position: UITextPosition, offset: Int) -> UITextPosition? {
        let moved = self.offset(of: position) + offset
        return (0...documentLength).contains(moved) ? RemoteDesktopTextPosition(moved) : nil
    }

    func position(from position: UITextPosition, in direction: UITextLayoutDirection, offset: Int)
        -> UITextPosition?
    {
        switch direction {
        case .left, .up: return self.position(from: position, offset: -offset)
        default: return self.position(from: position, offset: offset)
        }
    }

    func compare(_ position: UITextPosition, to other: UITextPosition) -> ComparisonResult {
        let first = offset(of: position)
        let second = offset(of: other)
        if first == second { return .orderedSame }
        return first < second ? .orderedAscending : .orderedDescending
    }

    func offset(from: UITextPosition, to toPosition: UITextPosition) -> Int {
        offset(of: toPosition) - offset(of: from)
    }

    func position(within range: UITextRange, farthestIn direction: UITextLayoutDirection) -> UITextPosition? {
        switch direction {
        case .left, .up: return range.start
        default: return range.end
        }
    }

    func characterRange(byExtending position: UITextPosition, in direction: UITextLayoutDirection)
        -> UITextRange?
    {
        let at = offset(of: position)
        switch direction {
        case .left, .up: return RemoteDesktopTextRange(0, at)
        default: return RemoteDesktopTextRange(at, documentLength)
        }
    }

    func baseWritingDirection(for position: UITextPosition, in direction: UITextStorageDirection)
        -> NSWritingDirection
    {
        .leftToRight
    }

    func setBaseWritingDirection(_ writingDirection: NSWritingDirection, for range: UITextRange) {}

    // MARK: Geometry: the view's own corner

    func firstRect(for range: UITextRange) -> CGRect {
        bounds
    }

    func caretRect(for position: UITextPosition) -> CGRect {
        CGRect(x: 0, y: 0, width: 1, height: bounds.height)
    }

    func selectionRects(for range: UITextRange) -> [UITextSelectionRect] {
        []
    }

    func closestPosition(to point: CGPoint) -> UITextPosition? {
        endOfDocument
    }

    func closestPosition(to point: CGPoint, within range: UITextRange) -> UITextPosition? {
        range.end
    }

    func characterRange(at point: CGPoint) -> UITextRange? {
        nil
    }

    /// Take the focus and raise the phone's keyboard.
    func showKeyboard() {
        becomeFirstResponder()
    }

    /// Put the phone's keyboard away and let the focus go.
    func hideKeyboard() {
        resignFirstResponder()
    }

    private var documentLength: Int {
        ((connection?.marked ?? "") as NSString).length
    }

    private func offset(of position: UITextPosition) -> Int {
        min(max((position as? RemoteDesktopTextPosition)?.offset ?? 0, 0), documentLength)
    }

    private static func keyCode(_ usage: UIKeyboardHIDUsage) -> String? {
        switch usage {
        case .keyboardEscape: return RemoteDesktopKey.escape.code
        case .keyboardLeftArrow: return RemoteDesktopKey.left.code
        case .keyboardRightArrow: return RemoteDesktopKey.right.code
        case .keyboardUpArrow: return RemoteDesktopKey.up.code
        case .keyboardDownArrow: return RemoteDesktopKey.down.code
        case .keyboardDeleteForward: return RemoteDesktopKey.delete
        default: return nil
        }
    }
}
