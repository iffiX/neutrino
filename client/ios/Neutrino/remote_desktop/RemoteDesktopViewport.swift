import Foundation

/// Where the remote picture sits in the viewer: fitted whole at zoom 1, larger when pinched, and never moved so far
/// that an edge leaves a gap it could fill. While the keyboard covers the viewer's lower part, the picture may move
/// up until its bottom edge reaches the keyboard.
struct RemoteDesktopViewport: Equatable {
    /// The viewer's width, in points.
    var viewWidth = 0.0

    /// The viewer's height, in points.
    var viewHeight = 0.0

    /// The remote picture's width, in its pixels; 0 before the first frame.
    var frameWidth = 0

    /// The remote picture's height.
    var frameHeight = 0

    /// The scale over the fitted one, from 1 to `RemoteDesktop.zoomMax`.
    var zoom = 1.0

    /// Where the picture's left edge is, in the viewer's points.
    var left = 0.0

    /// Where the picture's top edge is.
    var top = 0.0

    /// How much of the viewer's lower part the keyboard covers, in the viewer's points.
    var covered = 0.0

    /// Viewer points per picture pixel.
    var scale: Double { fitScale * zoom }

    /// The picture's drawn width, in the viewer's points.
    var drawnWidth: Double { hasFrame ? Double(frameWidth) * scale : viewWidth }

    /// The picture's drawn height.
    var drawnHeight: Double { hasFrame ? Double(frameHeight) * scale : viewHeight }

    private var hasFrame: Bool { frameWidth > 0 && frameHeight > 0 && viewWidth > 0 && viewHeight > 0 }

    private var fitScale: Double {
        hasFrame ? min(viewWidth / Double(frameWidth), viewHeight / Double(frameHeight)) : 1
    }

    /// The same picture in a viewer or of a frame of another size, fitted whole again.
    ///
    /// - Parameters:
    ///   - viewWidth: The viewer's width.
    ///   - viewHeight: The viewer's height.
    ///   - frameWidth: The picture's width.
    ///   - frameHeight: The picture's height.
    /// - Returns: This viewport when nothing changed, else a fitted one.
    func sized(viewWidth: Double, viewHeight: Double, frameWidth: Int, frameHeight: Int) -> RemoteDesktopViewport {
        let isSame =
            viewWidth == self.viewWidth && viewHeight == self.viewHeight && frameWidth == self.frameWidth
            && frameHeight == self.frameHeight
        if isSame { return self }
        return RemoteDesktopViewport(
            viewWidth: viewWidth, viewHeight: viewHeight, frameWidth: frameWidth, frameHeight: frameHeight,
            covered: covered
        ).clamped()
    }

    /// Zoom by a factor around a point that stays under the fingers.
    ///
    /// - Parameters:
    ///   - factor: The change of scale.
    ///   - focusX: The point's x in the viewer.
    ///   - focusY: The point's y in the viewer.
    /// - Returns: The zoomed viewport.
    func zoomed(by factor: Double, focusX: Double, focusY: Double) -> RemoteDesktopViewport {
        let next = min(max(zoom * factor, 1), RemoteDesktop.zoomMax)
        let ratio = next / zoom
        var moved = self
        moved.zoom = next
        moved.left = focusX - (focusX - left) * ratio
        moved.top = focusY - (focusY - top) * ratio
        return moved.clamped()
    }

    /// Move the picture with the fingers.
    ///
    /// - Parameters:
    ///   - dx: The move to the right, in viewer points.
    ///   - dy: The move down.
    /// - Returns: The moved viewport.
    func panned(dx: Double, dy: Double) -> RemoteDesktopViewport {
        var moved = self
        moved.left += dx
        moved.top += dy
        return moved.clamped()
    }

    /// The same picture with another part of the viewer covered by the keyboard; the picture keeps its size and
    /// place while that place is still allowed.
    ///
    /// - Parameter height: How much of the viewer's lower part the keyboard covers, 0 for none.
    /// - Returns: The viewport.
    func covering(_ height: Double) -> RemoteDesktopViewport {
        if height == covered { return self }
        var moved = self
        moved.covered = max(height, 0)
        return moved.clamped()
    }

    /// The picture pixel under a point of the viewer, kept inside the picture.
    ///
    /// - Parameters:
    ///   - x: The point's x in the viewer.
    ///   - y: The point's y in the viewer.
    /// - Returns: The pixel's column and row.
    func toFrame(x: Double, y: Double) -> (x: Int, y: Int) {
        guard hasFrame else { return (0, 0) }
        let column = min(max(Int((x - left) / scale), 0), frameWidth - 1)
        let row = min(max(Int((y - top) / scale), 0), frameHeight - 1)
        return (column, row)
    }

    private func clamped() -> RemoteDesktopViewport {
        var moved = self
        moved.left = Self.edge(left, view: viewWidth, drawn: drawnWidth, hidden: 0)
        moved.top = Self.edge(top, view: viewHeight, drawn: drawnHeight, hidden: covered)
        return moved
    }

    private static func edge(_ start: Double, view: Double, drawn: Double, hidden: Double) -> Double {
        let highest = drawn <= view ? (view - drawn) / 2 : 0
        let lowest = min(highest, view - hidden - drawn)
        return min(max(start, lowest), highest)
    }
}
