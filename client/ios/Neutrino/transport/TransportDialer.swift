import Foundation

/// Opens connections to the transport's local socket.
protocol TransportDialer: AnyObject {
    /// Open one connection.
    ///
    /// - Returns: Its descriptor, non-blocking, before its first line.
    /// - Throws: `ClientError.refused` with `hub_unreachable {detail}` when the socket does not take it.
    func dial() throws -> Int32
}
