import SwiftTerm
import SwiftUI

/// The terminal's box: the shown tab's terminal view, the other tabs' views kept aside with their output. A switch
/// of tabs with the keyboard up hands the typing to the tab now shown, and the keyboard stays.
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
        let shown = container.subviews
        let isTyping = view.isFirstResponder || shown.contains { $0.isFirstResponder }
        view.frame = container.bounds
        view.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        container.addSubview(view)
        if isTyping { _ = view.becomeFirstResponder() }
        for old in shown where old !== view { old.removeFromSuperview() }
        DispatchQueue.main.async { cache.reportSize(of: sessionId) }
    }
}
