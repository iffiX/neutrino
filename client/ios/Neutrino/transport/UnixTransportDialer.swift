import Foundation

#if canImport(Darwin)
    import Darwin
#else
    import Glibc
#endif

/// Connections to the transport's Unix socket.
final class UnixTransportDialer: TransportDialer {
    private let path: String

    /// Dial one socket.
    ///
    /// - Parameter path: The socket's path, as the library started on it.
    init(path: String) {
        self.path = path
    }

    func dial() throws -> Int32 {
        let descriptor = socket(AF_UNIX, ForwardSocket.streamType, 0)
        guard descriptor >= 0 else { throw failure("socket") }
        var address = sockaddr_un()
        address.sun_family = sa_family_t(AF_UNIX)
        let bytes = Array(path.utf8)
        let capacity = MemoryLayout.size(ofValue: address.sun_path)
        guard bytes.count < capacity else {
            close(descriptor)
            throw ClientError.refusal(Channel.codeHubUnreachable, ["detail": "the socket's path is too long"])
        }
        withUnsafeMutableBytes(of: &address.sun_path) { raw in
            raw.copyBytes(from: bytes)
            raw[bytes.count] = 0
        }
        #if canImport(Darwin)
            address.sun_len = UInt8(MemoryLayout<sockaddr_un>.size)
        #endif
        let connected = withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                connect(descriptor, $0, socklen_t(MemoryLayout<sockaddr_un>.size))
            }
        }
        guard connected == 0 else {
            let error = failure("connect")
            close(descriptor)
            throw error
        }
        ForwardSocket.prepare(descriptor)
        return descriptor
    }

    private func failure(_ call: String) -> ClientError {
        .refusal(Channel.codeHubUnreachable, ["detail": "\(call): \(String(cString: strerror(errno)))"])
    }
}
