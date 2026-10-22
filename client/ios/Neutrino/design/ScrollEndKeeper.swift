import Combine
import SwiftUI
import UIKit

/// Keeps the scroll view it is drawn in at its end while the keyboard slides: at the slide's start, and at every
/// change of the scroll view's size or of its content's size during it, so no frame shows the page anywhere else.
/// Drawn as the background of a scroll view's content.
struct ScrollEndKeeper: UIViewRepresentable {
    /// The keyboard's slide.
    let keyboard: KeyboardMotion

    func makeUIView(context: Context) -> KeeperView {
        KeeperView(keyboard: keyboard)
    }

    func updateUIView(_ view: KeeperView, context: Context) {}

    /// The view that finds the scroll view around it and moves it to its end.
    final class KeeperView: UIView {
        private let keyboard: KeyboardMotion
        private var start: AnyCancellable?
        private var watches: [NSKeyValueObservation] = []
        private weak var scroll: UIScrollView?

        /// Keep the scroll view around this view at its end while the keyboard slides.
        ///
        /// - Parameter keyboard: The keyboard's slide.
        init(keyboard: KeyboardMotion) {
            self.keyboard = keyboard
            super.init(frame: .zero)
            isUserInteractionEnabled = false
            start = keyboard.$isMoving.removeDuplicates().filter { $0 }.sink { [weak self] _ in self?.keepEnd() }
        }

        required init?(coder: NSCoder) {
            nil
        }

        override func didMoveToWindow() {
            super.didMoveToWindow()
            watches = []
            var ancestor = superview
            while let view = ancestor, !(view is UIScrollView) { ancestor = view.superview }
            scroll = ancestor as? UIScrollView
            guard window != nil, let scroll else { return }
            watches = [
                scroll.observe(\.contentSize) { [weak self] _, _ in self?.keepEndWhileMoving() },
                scroll.observe(\.bounds) { [weak self] _, _ in self?.keepEndWhileMoving() },
                scroll.observe(\.frame) { [weak self] _, _ in self?.keepEndWhileMoving() },
                scroll.observe(\.center) { [weak self] _, _ in self?.keepEndWhileMoving() },
            ]
        }

        private func keepEndWhileMoving() {
            if keyboard.isMoving { keepEnd() }
        }

        private func keepEnd() {
            guard let scroll else { return }
            let top = -scroll.adjustedContentInset.top
            let end = max(top, scroll.contentSize.height - scroll.bounds.height + scroll.adjustedContentInset.bottom)
            if abs(scroll.contentOffset.y - end) > 0.5 {
                scroll.setContentOffset(CGPoint(x: scroll.contentOffset.x, y: end), animated: false)
            }
        }
    }
}
