import Foundation

/// One mouse event as RustDesk takes it: a column and a row in the remote picture, or the wheel's steps, and a
/// mask with the type in its low three bits and the buttons above.
struct RemoteDesktopMouse: Equatable {
    /// The column in the remote picture, or the horizontal wheel steps.
    let x: Int

    /// The row, or the vertical wheel steps.
    let y: Int

    /// The type and the buttons.
    let mask: Int

    /// A tap: the pointer moves there, then the left button goes down and up.
    ///
    /// - Parameters:
    ///   - x: The column.
    ///   - y: The row.
    /// - Returns: The events.
    static func tap(x: Int, y: Int) -> [RemoteDesktopMouse] {
        click(x: x, y: y, button: RemoteDesktop.mouseLeft)
    }

    /// A long press: the right button's click there.
    ///
    /// - Parameters:
    ///   - x: The column.
    ///   - y: The row.
    /// - Returns: The events.
    static func longPress(x: Int, y: Int) -> [RemoteDesktopMouse] {
        click(x: x, y: y, button: RemoteDesktop.mouseRight)
    }

    /// The start of a one-finger drag: the left button goes down where the finger landed.
    ///
    /// - Parameters:
    ///   - x: The column.
    ///   - y: The row.
    /// - Returns: The events.
    static func dragStart(x: Int, y: Int) -> [RemoteDesktopMouse] {
        [
            RemoteDesktopMouse(x: x, y: y, mask: RemoteDesktop.mouseMove),
            RemoteDesktopMouse(x: x, y: y, mask: RemoteDesktop.mouseDown | RemoteDesktop.mouseLeft),
        ]
    }

    /// The finger moving during a drag.
    ///
    /// - Parameters:
    ///   - x: The column.
    ///   - y: The row.
    /// - Returns: The event.
    static func dragMove(x: Int, y: Int) -> RemoteDesktopMouse {
        RemoteDesktopMouse(x: x, y: y, mask: RemoteDesktop.mouseMove)
    }

    /// The end of a drag: the left button comes up where the finger left.
    ///
    /// - Parameters:
    ///   - x: The column.
    ///   - y: The row.
    /// - Returns: The event.
    static func dragEnd(x: Int, y: Int) -> RemoteDesktopMouse {
        RemoteDesktopMouse(x: x, y: y, mask: RemoteDesktop.mouseUp | RemoteDesktop.mouseLeft)
    }

    /// The wheel steps a two-finger scroll has travelled, and what is left over.
    ///
    /// - Parameter travel: The fingers' downward travel not yet sent, in points.
    /// - Returns: The wheel event, or nil under one step, and the travel still unsent.
    static func wheel(travel: Double) -> (RemoteDesktopMouse?, Double) {
        let steps = Int(travel / RemoteDesktop.scrollStepPoints)
        if steps == 0 { return (nil, travel) }
        let event = RemoteDesktopMouse(x: 0, y: steps, mask: RemoteDesktop.mouseWheel)
        return (event, travel - Double(steps) * RemoteDesktop.scrollStepPoints)
    }

    private static func click(x: Int, y: Int, button: Int) -> [RemoteDesktopMouse] {
        [
            RemoteDesktopMouse(x: x, y: y, mask: RemoteDesktop.mouseMove),
            RemoteDesktopMouse(x: x, y: y, mask: RemoteDesktop.mouseDown | button),
            RemoteDesktopMouse(x: x, y: y, mask: RemoteDesktop.mouseUp | button),
        ]
    }
}
