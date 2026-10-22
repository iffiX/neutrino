import Combine
import UIKit

/// The keyboard's slide, followed frame by frame: how much of the window's safe area it covers, from the safe area's
/// foot, at every frame the screen draws, so the page laid out above it moves in step with it. A probe view slides
/// with the keyboard's own duration and curve, and each frame reads where the probe is.
final class KeyboardMotion: NSObject, ObservableObject {
    /// The points of the window's safe area the keyboard covers now, from the safe area's foot.
    @Published private(set) var overlap = 0.0

    /// Whether the keyboard is sliding, until the pages are laid out at the slide's end.
    @Published private(set) var isMoving = false

    private let probe = UIView()
    private var link: CADisplayLink?
    private var target = 0.0
    private var slide = 0

    override init() {
        super.init()
        probe.isUserInteractionEnabled = false
        probe.alpha = 0
        NotificationCenter.default.addObserver(
            self, selector: #selector(keyboardWillChangeFrame(_:)),
            name: UIResponder.keyboardWillChangeFrameNotification, object: nil)
    }

    /// The points of a window's safe area a keyboard covers, from the safe area's foot; none for a keyboard that does
    /// not reach the window's foot, as a floating one on a tablet.
    ///
    /// - Parameters:
    ///   - keyboard: The keyboard's frame, in the window's coordinates.
    ///   - windowHeight: The window's height.
    ///   - safeBottom: The window's safe area inset at its foot.
    /// - Returns: The points covered.
    static func overlap(of keyboard: CGRect, windowHeight: Double, safeBottom: Double) -> Double {
        guard keyboard.maxY >= windowHeight - 1 else { return 0 }
        return max(0, windowHeight - safeBottom - keyboard.minY)
    }

    @objc private func keyboardWillChangeFrame(_ note: Notification) {
        guard let info = note.userInfo,
            let frame = (info[UIResponder.keyboardFrameEndUserInfoKey] as? NSValue)?.cgRectValue,
            let window = Self.keyWindow
        else { return }
        let keyboard = window.convert(frame, from: window.screen.coordinateSpace)
        let next = Self.overlap(
            of: keyboard, windowHeight: window.bounds.height, safeBottom: window.safeAreaInsets.bottom)
        guard next != target else { return }
        target = next
        slide += 1
        let current = slide
        let duration = info[UIResponder.keyboardAnimationDurationUserInfoKey] as? Double ?? 0
        let curve = info[UIResponder.keyboardAnimationCurveUserInfoKey] as? UInt ?? 7
        isMoving = true
        probe.layer.removeAllAnimations()
        guard duration > 0 else {
            stopFollowing()
            overlap = next
            DispatchQueue.main.async { if current == self.slide { self.isMoving = false } }
            return
        }
        if probe.superview !== window { window.addSubview(probe) }
        probe.frame = CGRect(x: 0, y: overlap, width: 1, height: 1)
        UIView.animate(
            withDuration: duration, delay: 0, options: UIView.AnimationOptions(rawValue: curve << 16),
            animations: { self.probe.frame.origin.y = next },
            completion: { _ in
                guard current == self.slide else { return }
                self.stopFollowing()
                self.overlap = next
                DispatchQueue.main.async { if current == self.slide { self.isMoving = false } }
            })
        if link == nil {
            let link = CADisplayLink(target: self, selector: #selector(frameDrawn))
            link.add(to: .main, forMode: .common)
            self.link = link
        }
    }

    private static var keyWindow: UIWindow? {
        let windows = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.flatMap(\.windows)
        return windows.first(where: \.isKeyWindow) ?? windows.first
    }

    @objc private func frameDrawn() {
        guard let shown = probe.layer.presentation()?.frame.origin.y, shown != probe.frame.origin.y else { return }
        overlap = shown
    }

    private func stopFollowing() {
        link?.invalidate()
        link = nil
    }
}
