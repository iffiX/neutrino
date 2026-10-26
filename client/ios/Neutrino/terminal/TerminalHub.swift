import Foundation

/// What a terminal tab asks of one hub while it is connected.
protocol TerminalHub: AnyObject {
    /// Open a `shell` stream, its records both ways.
    ///
    /// - Parameter open: The stream's `open` record.
    /// - Returns: The stream, or the refusal.
    func openShell(_ open: [String: JSONValue]) -> Result<TransportStream, ClientError>

    /// Set whether a kept shell stays and whether others can attach to it.
    ///
    /// - Parameters:
    ///   - sessionId: The session.
    ///   - isPersistent: Whether it outlives every window.
    ///   - isShared: Whether every client with terminal rights on the machine lists it.
    ///   - completion: Called with the reply, or its refusal.
    func persist(
        sessionId: String, isPersistent: Bool, isShared: Bool,
        completion: @escaping (Result<[String: JSONValue], ClientError>) -> Void)

    /// End a kept shell.
    ///
    /// - Parameters:
    ///   - sessionId: The session.
    ///   - completion: Called with the reply, or its refusal.
    func stopSession(_ sessionId: String, completion: @escaping (Result<[String: JSONValue], ClientError>) -> Void)
}
