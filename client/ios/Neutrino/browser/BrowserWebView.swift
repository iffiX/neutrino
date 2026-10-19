import SwiftUI
import WebKit

/// The in-app browser's WebKit view, at one forward's loopback address; every page shares one cookie store.
struct BrowserWebView: UIViewRepresentable {
    /// The page.
    let target: BrowserTarget

    func makeCoordinator() -> BrowserNavigationDelegate {
        BrowserNavigationDelegate()
    }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.navigationDelegate = context.coordinator
        view.allowsBackForwardNavigationGestures = true
        load(target, in: view)
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {
        if view.url == nil && !view.isLoading { load(target, in: view) }
    }

    private func load(_ target: BrowserTarget, in view: WKWebView) {
        guard let url = URL(string: target.url) else { return }
        view.load(URLRequest(url: url))
    }
}
