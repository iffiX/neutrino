import Darwin
import Foundation

/// A program on the phone that connects to a forward on the loopback.
final class LoopbackClient {
    private let descriptor: Int32

    /// Connect to a loopback port.
    ///
    /// - Parameter port: The port.
    init?(port: Int) {
        descriptor = socket(AF_INET, SOCK_STREAM, 0)
        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = in_port_t(UInt16(port).bigEndian)
        address.sin_addr = in_addr(s_addr: inet_addr("127.0.0.1"))
        let connected = withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                connect(descriptor, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        var quiet: Int32 = 1
        setsockopt(descriptor, SOL_SOCKET, SO_NOSIGPIPE, &quiet, socklen_t(MemoryLayout<Int32>.size))
        var wait = timeval(tv_sec: 0, tv_usec: 300_000)
        setsockopt(descriptor, SOL_SOCKET, SO_RCVTIMEO, &wait, socklen_t(MemoryLayout<timeval>.size))
        guard connected == 0 else { return nil }
    }

    deinit {
        close(descriptor)
    }

    /// Write bytes.
    ///
    /// - Parameter bytes: The bytes.
    func write(_ bytes: Data) {
        _ = bytes.withUnsafeBytes { send(descriptor, $0.baseAddress, $0.count, 0) }
    }

    /// Read what has arrived, waiting a little.
    ///
    /// - Returns: The bytes; empty when nothing came.
    func read() -> Data {
        var buffer = [UInt8](repeating: 0, count: 65536)
        let count = buffer.withUnsafeMutableBytes { recv(descriptor, $0.baseAddress, $0.count, 0) }
        return count > 0 ? Data(buffer[0..<count]) : Data()
    }
}
