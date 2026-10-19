import Foundation

/// A managed machine a new terminal opens on, by its hub and its id.
struct TerminalMachine: Equatable, Hashable {
    /// The hub.
    let bindingId: String

    /// The machine.
    let deviceId: String
}
