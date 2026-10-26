import Foundation

/// What the transport says about one hub, in the order it says it.
enum TransportEvent: Equatable {
    /// A round's winner completed its handshake and opened its control stream; `hello` goes next. On a hub whose
    /// session is live, it is a move to a better path.
    case sessionOpen(address: String, path: String, handshakeMs: Int)
    /// A round ended with no session: the code, nil when it carried none, and the seconds until the transport's
    /// next round, 0 when none follows.
    case roundEnd(ClientError?, nextRoundSeconds: Double)
    /// The session ended: the refusal that ended it, nil when the connection dropped.
    case sessionEnd(ClientError?)
    /// One frame from the hub, with its `type`.
    case frame([String: JSONValue])
    /// The local channel was opened again after it dropped: every hub is dialled again.
    case restarted
}
