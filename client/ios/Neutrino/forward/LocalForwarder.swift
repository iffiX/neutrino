import Foundation

/// What holds the loopback listeners of the apps and the panel: each accepted connection a stream on a hub's
/// session.
protocol LocalForwarder: AnyObject {
    /// Listen on `127.0.0.1:<port>` and open a stream with `open` for each connection, or one for a UDP listener.
    ///
    /// - Parameters:
    ///   - bindingId: The hub whose session carries the streams.
    ///   - port: The loopback number, 0 for the system's pick.
    ///   - protocol: `tcp` or `udp`.
    ///   - open: The streams' `open` record, `{kind: connect, ...}`.
    ///   - completion: Called with the number listened on, or the refusal: `port_taken {port}` when it is held.
    func start(
        bindingId: String, port: Int, protocol: String, open: [String: JSONValue],
        completion: @escaping (Result<Int, ClientError>) -> Void)

    /// Close a listener and its streams.
    ///
    /// - Parameters:
    ///   - port: The loopback number.
    ///   - protocol: `tcp` or `udp`.
    func stop(port: Int, protocol: String)
}
