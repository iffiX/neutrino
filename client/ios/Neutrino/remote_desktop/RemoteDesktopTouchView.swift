import UIKit

/// The surface over the picture that reads the fingers: a tap, a long press, a one-finger drag, and two fingers,
/// each reported in the view's points.
final class RemoteDesktopTouchView: UIView {
    /// A tap where the finger lifted.
    var onTap: ((CGPoint) -> Void)?

    /// A long press where the finger rests.
    var onLongPress: ((CGPoint) -> Void)?

    /// A one-finger drag started where the finger landed.
    var onDragStart: ((CGPoint) -> Void)?

    /// The dragging finger moved.
    var onDragMove: ((CGPoint) -> Void)?

    /// The dragging finger left.
    var onDragEnd: ((CGPoint) -> Void)?

    /// Two fingers moved: the point between them and their spread.
    var onTwoFingers: ((CGPoint, Double) -> Void)?

    /// The two fingers left.
    var onTwoFingersEnd: (() -> Void)?

    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundColor = .clear
        isMultipleTouchEnabled = true
        let longPress = UILongPressGestureRecognizer(target: self, action: #selector(pressed(_:)))
        let tap = UITapGestureRecognizer(target: self, action: #selector(tapped(_:)))
        tap.require(toFail: longPress)
        let drag = UIPanGestureRecognizer(target: self, action: #selector(dragged(_:)))
        drag.maximumNumberOfTouches = 1
        let twoFingers = UIPanGestureRecognizer(target: self, action: #selector(twoFingered(_:)))
        twoFingers.minimumNumberOfTouches = 2
        twoFingers.maximumNumberOfTouches = 2
        for recognizer in [longPress, tap, drag, twoFingers] { addGestureRecognizer(recognizer) }
    }

    required init?(coder: NSCoder) {
        return nil
    }

    @objc private func tapped(_ recognizer: UITapGestureRecognizer) {
        if recognizer.state == .ended { onTap?(recognizer.location(in: self)) }
    }

    @objc private func pressed(_ recognizer: UILongPressGestureRecognizer) {
        if recognizer.state == .began { onLongPress?(recognizer.location(in: self)) }
    }

    @objc private func dragged(_ recognizer: UIPanGestureRecognizer) {
        let point = recognizer.location(in: self)
        switch recognizer.state {
        case .began:
            let moved = recognizer.translation(in: self)
            onDragStart?(CGPoint(x: point.x - moved.x, y: point.y - moved.y))
            onDragMove?(point)
        case .changed:
            onDragMove?(point)
        case .ended, .cancelled, .failed:
            onDragEnd?(point)
        default:
            break
        }
    }

    @objc private func twoFingered(_ recognizer: UIPanGestureRecognizer) {
        switch recognizer.state {
        case .began, .changed:
            guard recognizer.numberOfTouches >= 2 else { return }
            let first = recognizer.location(ofTouch: 0, in: self)
            let second = recognizer.location(ofTouch: 1, in: self)
            let centre = CGPoint(x: (first.x + second.x) / 2, y: (first.y + second.y) / 2)
            onTwoFingers?(centre, Double(hypot(first.x - second.x, first.y - second.y)))
        case .ended, .cancelled, .failed:
            onTwoFingersEnd?()
        default:
            break
        }
    }
}
