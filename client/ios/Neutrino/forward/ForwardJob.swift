import Foundation

/// The job running on a forwarded entry's row, each worded as its button's in-progress word.
enum ForwardJob: String {
    /// Open on a web entry, or Panel on a hub row: the forward, the token where one is needed, then the browser.
    case opening = "ui.job.opening"
    /// Disconnect: the listener and its connections are being closed.
    case disconnecting = "ui.job.disconnecting"
}
