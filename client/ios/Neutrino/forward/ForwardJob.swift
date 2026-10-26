import Foundation

/// The job running on an app's row, or on a hub's Panel, each worded as its button's in-progress word.
enum ForwardJob: String {
    /// Use on an app, its forwards; Open on an app or Panel on a hub row: the token where one is needed, then the
    /// browser.
    case opening = "ui.job.opening"
    /// Stop on an app: every forward of the app is being closed.
    case disconnecting = "ui.job.disconnecting"
}
