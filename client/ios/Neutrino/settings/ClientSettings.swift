import Foundation

/// The app's own settings: the language and the palette.
struct ClientSettings: Equatable {
    /// One of `Client.languages`.
    var language: String

    /// One of `Client.themes`.
    var theme: String
}
