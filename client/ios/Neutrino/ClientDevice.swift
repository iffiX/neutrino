import Foundation

/// What the phone and the build say about this installation.
struct ClientDevice: Equatable {
    /// The device name iOS gives the app, such as `iPhone`.
    let name: String

    /// The architecture, `arm64` on an iPhone.
    let arch: String

    /// The iOS release, such as `16.7`.
    let osVersion: String

    /// The app's version, as the build stamped it.
    let appVersion: String
}
