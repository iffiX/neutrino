import SwiftUI

/// One of the viewer's UIKit views, made by the viewer's model and placed in the page as it is.
struct RemoteDesktopHostedView: UIViewRepresentable {
    /// The view.
    let view: UIView

    func makeUIView(context: Context) -> UIView {
        view
    }

    func updateUIView(_ view: UIView, context: Context) {}
}
