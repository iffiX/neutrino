import Foundation

/// A forward's listener stopped: a UDP forward whose stream the hub or the agent closed with a code.
struct TransportForwardEnd: Equatable {
    /// The address it listened on, `127.0.0.1:<port>`.
    let listen: String

    /// `tcp` or `udp`.
    let `protocol`: String

    /// Why, nil when it carries no code.
    let refusal: ClientError?
}
