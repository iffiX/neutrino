import Foundation

/// One session a hub lists, with where it runs.
struct TerminalListing: Equatable {
    /// The hub.
    let bindingId: String

    /// The machine.
    let deviceId: String

    /// The machine's name.
    let machineName: String

    /// The session as listed.
    let session: ChannelTerminalSession
}
