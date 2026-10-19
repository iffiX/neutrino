import Foundation

/// How this phone reaches a hub's pinned port: the two HTTP calls, and the socket. Every callback runs on the
/// main queue.
protocol HubTransport: AnyObject {
    /// One JSON request to the hub, over a connection checked against the pin before a byte leaves.
    ///
    /// - Parameters:
    ///   - baseUrl: The hub's address, `https://host:port`.
    ///   - path: The route.
    ///   - fingerprint: The pinned SHA-256.
    ///   - body: The request body.
    ///   - completion: Called with the answer's JSON, or the refusal: the `detail {code, params}` of an error
    ///     answer, `hub_untrusted` for another certificate, `hub_unreachable` for anything on the way.
    func post(
        baseUrl: String, path: String, fingerprint: String, body: [String: JSONValue],
        completion: @escaping (Result<[String: JSONValue], ClientError>) -> Void)

    /// Open the socket; what happens on it goes to its `onEvent`, set by the caller before the main queue turns.
    ///
    /// - Parameters:
    ///   - baseUrl: The hub's address, `https://host:port`.
    ///   - fingerprint: The pinned SHA-256.
    /// - Returns: The socket, to send on and close.
    func connect(baseUrl: String, fingerprint: String) -> ChannelSocket
}
