import UIKit

/// A place in the viewer's text input: an offset, in UTF-16 units, into the text the keyboard marks.
final class RemoteDesktopTextPosition: UITextPosition {
    /// The offset.
    let offset: Int

    /// Make a position.
    ///
    /// - Parameter offset: The offset.
    init(_ offset: Int) {
        self.offset = offset
    }
}
