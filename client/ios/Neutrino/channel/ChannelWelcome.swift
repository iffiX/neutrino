import Foundation

/// The hub's identity card.
struct ChannelWelcome: Equatable {
    /// The hub's protocol number.
    let protocolNumber: Int
    /// `hub`.
    let role: String
    /// The hub's id.
    let id: String
    /// The hub's name.
    let name: String
    /// `neutrino_hub/<version>`.
    let software: String
}
