import SwiftUI

/// A monitor's outline with an empty screen on a stand, the Remote desktops page's icon, as Android draws it on a
/// 24-unit square.
struct MonitorShape: Shape {
    func path(in rect: CGRect) -> Path {
        let unit = min(rect.width, rect.height) / 24
        let left = rect.midX - 12 * unit
        let top = rect.midY - 12 * unit
        func point(_ x: CGFloat, _ y: CGFloat) -> CGPoint {
            CGPoint(x: left + x * unit, y: top + y * unit)
        }
        var path = Path()
        path.addRoundedRect(
            in: CGRect(origin: point(3, 4), size: CGSize(width: 18 * unit, height: 12 * unit)),
            cornerSize: CGSize(width: 2 * unit, height: 2 * unit))
        path.move(to: point(12, 16))
        path.addLine(to: point(12, 20))
        path.move(to: point(9, 20))
        path.addLine(to: point(15, 20))
        return path
    }
}
