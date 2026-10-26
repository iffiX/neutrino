import Foundation

/// One address a round dials, with the way it reaches the hub.
struct ChannelCandidate: Equatable {
    /// `tcp://<host>:<port>`, an IPv6 host in brackets.
    let address: String

    /// The path's word, one of `ChannelPath`'s.
    let path: String
}
