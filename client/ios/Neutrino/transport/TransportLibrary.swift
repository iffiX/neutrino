import Foundation

/// The transport the app embeds: one call starts it on its local channel, one stops it.
protocol TransportLibrary: AnyObject {
    /// Start the transport, listening on its local channel.
    ///
    /// - Parameters:
    ///   - directory: The app's own data directory, where the transport makes `transport.sock`.
    ///   - secret: The 64 hex characters every local connection opens with.
    /// - Returns: The path of the socket the transport listens on: in `directory`, or in a directory of its own
    ///   when that path is past the system's limit for a socket's path.
    /// - Throws: `ClientError.refused` with `transport_missing` in a build with no transport, and
    ///   `transport_failed {detail}` when it could not start.
    func start(directory: String, secret: String) throws -> String

    /// Stop the transport: every session and every forward ends.
    func stop()
}
