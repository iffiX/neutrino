import Foundation

/// One two-finger gesture on the viewer, decided once by its first change past `RemoteDesktop.pinchSlopPoints`: a
/// pinch when the fingers' spread changes first, which zooms and moves the picture, and a scroll when their centre
/// moves first, which turns the wheel by the centre's vertical travel.
struct RemoteDesktopTwoFingers {
    /// What the gesture was decided to be.
    enum Mode: Equatable {
        /// Neither yet.
        case undecided
        /// A pinch.
        case pinch
        /// A scroll.
        case scroll
    }

    /// What one move of the fingers does.
    enum Step: Equatable {
        /// Zoom by a factor around a point and move the picture.
        case pinch(factor: Double, focusX: Double, focusY: Double, dx: Double, dy: Double)
        /// Turn the wheel.
        case wheel(RemoteDesktopMouse)
    }

    /// What the gesture is.
    private(set) var mode = Mode.undecided

    private var origin: (x: Double, y: Double, spread: Double)?
    private var previous: (x: Double, y: Double, spread: Double)?
    private var travel = 0.0

    /// The fingers moved.
    ///
    /// - Parameters:
    ///   - centreX: The x of the point between the two fingers, in the viewer.
    ///   - centreY: Its y.
    ///   - spread: The distance between the fingers.
    /// - Returns: What the move does, or nil while undecided or under one wheel step.
    mutating func move(centreX: Double, centreY: Double, spread: Double) -> Step? {
        let now = (x: centreX, y: centreY, spread: spread)
        let before = previous ?? now
        let first = origin ?? now
        origin = first
        previous = now
        if mode == .undecided {
            if abs(spread - first.spread) > RemoteDesktop.pinchSlopPoints {
                mode = .pinch
            } else if hypot(centreX - first.x, centreY - first.y) > RemoteDesktop.pinchSlopPoints {
                mode = .scroll
            }
        }
        switch mode {
        case .undecided:
            return nil
        case .pinch:
            let factor = before.spread > 0 ? spread / before.spread : 1
            return .pinch(
                factor: factor, focusX: centreX, focusY: centreY, dx: centreX - before.x, dy: centreY - before.y)
        case .scroll:
            let (wheel, rest) = RemoteDesktopMouse.wheel(travel: travel + (centreY - before.y))
            travel = rest
            return wheel.map { .wheel($0) }
        }
    }
}
