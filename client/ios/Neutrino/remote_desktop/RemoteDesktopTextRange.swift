import UIKit

/// A run of the viewer's text input, between two offsets into the text the keyboard marks.
final class RemoteDesktopTextRange: UITextRange {
    private let from: RemoteDesktopTextPosition
    private let to: RemoteDesktopTextPosition

    /// Make a range.
    ///
    /// - Parameters:
    ///   - start: Its first offset.
    ///   - end: The offset after its last unit.
    init(_ start: Int, _ end: Int) {
        from = RemoteDesktopTextPosition(min(start, end))
        to = RemoteDesktopTextPosition(max(start, end))
    }

    override var start: UITextPosition { from }

    override var end: UITextPosition { to }

    override var isEmpty: Bool { from.offset == to.offset }

    /// The range as a Foundation range of UTF-16 units.
    var nsRange: NSRange { NSRange(location: from.offset, length: to.offset - from.offset) }
}
