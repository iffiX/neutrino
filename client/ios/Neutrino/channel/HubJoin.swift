import Foundation

/// The join a person started: running, or ended in a binding or a refusal.
struct HubJoin: Equatable {
    /// Whether the link is being checked and the binding written.
    var isJoining = false

    /// Why the last join failed, shown under the link until the next press.
    var refusal: ClientError?

    /// The binding the last join wrote, until the Join page has drawn it.
    var joinedId: String?
}
