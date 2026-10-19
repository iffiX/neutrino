import WebKit

/// What the in-app browser does on its own: it loads a page again when iOS ended its process in the background,
/// and it takes the certificate of a page on the loopback, whose bytes come through the pinned channel.
final class BrowserNavigationDelegate: NSObject, WKNavigationDelegate {
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        webView.reload()
    }

    func webView(_ webView: WKWebView, didReceive challenge: URLAuthenticationChallenge) async -> (
        URLSession.AuthChallengeDisposition, URLCredential?
    ) {
        guard challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust,
            challenge.protectionSpace.host == Forward.bindHost, let trust = challenge.protectionSpace.serverTrust
        else { return (.performDefaultHandling, nil) }
        return (.useCredential, URLCredential(trust: trust))
    }
}
