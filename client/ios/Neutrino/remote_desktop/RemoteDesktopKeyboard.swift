import Foundation

/// The phone's keyboard as the viewer sees it. A keyboard the system floats over the picture is shown and covers
/// no height.
struct RemoteDesktopKeyboard: Equatable {
    /// Whether the system shows the keyboard.
    var isShown = false

    /// The height in points it covers at the viewer's bottom edge, 0 for a floating keyboard or none.
    var height = 0.0

    /// The keyboard where the system is putting it.
    ///
    /// - Parameters:
    ///   - frame: The keyboard's frame at the end of its move, in the coordinates of the viewer, which fills the
    ///     screen.
    ///   - viewHeight: The viewer's height.
    /// - Returns: Shown while any of it is above the bottom edge, covering from its top edge down when it reaches
    ///   that edge.
    static func of(frame: CGRect, viewHeight: Double) -> RemoteDesktopKeyboard {
        let top = Double(frame.minY)
        let isShown = frame.height > 0 && top < viewHeight
        let isDocked = Double(frame.maxY) >= viewHeight - 1
        return RemoteDesktopKeyboard(isShown: isShown, height: isShown && isDocked ? viewHeight - top : 0)
    }
}
