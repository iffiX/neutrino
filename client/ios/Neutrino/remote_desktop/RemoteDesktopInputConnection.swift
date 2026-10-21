import Foundation

/// The phone keyboard's link to the viewer, behind the viewer's text input. Committed text is sent as text; text the
/// keyboard still marks, such as a pinyin composition, is sent nowhere until the keyboard commits it, and then once
/// as text; a commit replaces what was marked; a delete with nothing marked is Backspace.
final class RemoteDesktopInputConnection {
    private let sender: RemoteDesktopInputSender

    /// The text the keyboard marks now, empty when it marks none.
    private(set) var marked = ""

    /// Where the selection sits inside the marked text, in UTF-16 units.
    private(set) var selection = NSRange(location: 0, length: 0)

    /// Link the keyboard to a sender.
    ///
    /// - Parameter sender: Where the keys and the text go.
    init(sender: RemoteDesktopInputSender) {
        self.sender = sender
    }

    /// The keyboard committed text, which replaces what it marked.
    ///
    /// - Parameter text: The text.
    func insert(_ text: String) {
        setMarked("", selection: NSRange(location: 0, length: 0))
        sender.type(text)
    }

    /// The keyboard marks text it is still composing; none of it is sent.
    ///
    /// - Parameters:
    ///   - text: The marked text, empty for none.
    ///   - selection: Where the selection sits inside it.
    func setMarked(_ text: String, selection: NSRange) {
        marked = text
        let length = (text as NSString).length
        let location = min(max(selection.location, 0), length)
        self.selection = NSRange(location: location, length: min(max(selection.length, 0), length - location))
    }

    /// The keyboard finished composing: what it marked is sent once as text.
    func unmark() {
        let finished = marked
        setMarked("", selection: NSRange(location: 0, length: 0))
        if !finished.isEmpty { sender.type(finished) }
    }

    /// The delete key: the marked text loses its last character, or Backspace is sent when none is marked.
    func deleteBackward() {
        guard !marked.isEmpty else {
            sender.press(RemoteDesktopKey.backspace)
            return
        }
        let shorter = String(marked.dropLast())
        let length = (shorter as NSString).length
        setMarked(shorter, selection: NSRange(location: length, length: 0))
    }

    /// A key of a hardware keyboard that types no text, such as an arrow or Escape.
    ///
    /// - Parameter code: RustDesk's name for the key.
    func press(_ code: String) {
        sender.press(code)
    }
}
