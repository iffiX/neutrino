import Foundation

/// The app a local port dialog configures.
struct LocalPortTarget: Identifiable {
    /// The hub.
    let bindingId: String

    /// The app.
    let appId: String

    /// The app's title, in the dialog's title.
    let title: String

    /// The app's entries, one line each.
    let entries: [ChannelServiceEntry]

    /// `<binding>/<app>`.
    var id: String { "\(bindingId)/\(appId)" }
}
