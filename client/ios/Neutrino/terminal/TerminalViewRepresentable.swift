import SwiftTerm
import SwiftUI

/// The terminal's box: the shown tab's terminal view, the other tabs' views kept aside with their output.
struct TerminalViewRepresentable: UIViewRepresentable {
    /// The views of every tab.
    let cache: TerminalViewCache

    /// The tab shown.
    let sessionId: String

    func makeUIView(context: Context) -> UIView {
        let container = UIView()
        container.clipsToBounds = true
        return container
    }

    func updateUIView(_ container: UIView, context: Context) {
        let view = cache.view(of: sessionId)
        guard view.superview !== container else { return }
        for old in container.subviews { old.removeFromSuperview() }
        view.frame = container.bounds
        view.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        container.addSubview(view)
        DispatchQueue.main.async { cache.reportSize(of: sessionId) }
    }
}
