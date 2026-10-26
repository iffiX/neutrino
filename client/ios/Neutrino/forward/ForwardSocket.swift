import Foundation

#if canImport(Darwin)
    import Darwin
#else
    import Glibc
#endif

/// The POSIX calls the loopback forwards are made of: a listener on `127.0.0.1`, the probe of a free number,
/// and the reads and writes of an accepted connection, every descriptor non-blocking.
enum ForwardSocket {
    /// Listen on `127.0.0.1` at a number.
    ///
    /// - Parameter port: The number; 0 for any free one.
    /// - Returns: The listening descriptor and the number it is bound to.
    /// - Throws: `ClientError.refused` with `forward_failed {detail}` when the number cannot be bound.
    static func listenLoopback(port: Int) throws -> (descriptor: Int32, port: Int) {
        let descriptor = socket(AF_INET, streamType, 0)
        guard descriptor >= 0 else { throw failure("socket") }
        var isReused: Int32 = 1
        setsockopt(descriptor, SOL_SOCKET, SO_REUSEADDR, &isReused, socklen_t(MemoryLayout<Int32>.size))
        var address = loopback(port: port)
        let bound = withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                bind(descriptor, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        guard bound == 0, listen(descriptor, 128) == 0 else {
            let error = failure("bind \(Forward.bindHost):\(port)")
            close(descriptor)
            throw error
        }
        setNonBlocking(descriptor)
        return (descriptor, boundPort(descriptor))
    }

    /// Whether nothing listens on a number on any address of the phone now: a probe binds it on the IPv4
    /// wildcard address, then on the IPv6 one where the phone has IPv6, with sockets of the protocol, and closes
    /// them.
    ///
    /// - Parameters:
    ///   - port: The number.
    ///   - protocol: `tcp` or `udp`.
    ///   - isKept: Whether the table keeps the number for an entry already; such a number is probed with address
    ///     reuse, so this app's own closed connections still lingering on it do not count.
    /// - Returns: True when both probes could take it.
    static func isFree(port: Int, protocol: String, isKept: Bool) -> Bool {
        let type = `protocol` == Forward.protocolUdp ? datagramType : streamType
        return canBind(family: AF_INET, type: type, port: port, isReused: isKept, isFamilyRequired: true)
            && canBind(family: AF_INET6, type: type, port: port, isReused: isKept, isFamilyRequired: false)
    }

    /// Make a connected descriptor non-blocking, and keep a write to a closed peer from raising a signal.
    ///
    /// - Parameter descriptor: The connection.
    static func prepare(_ descriptor: Int32) {
        setNonBlocking(descriptor)
        #if canImport(Darwin)
            var isQuiet: Int32 = 1
            setsockopt(descriptor, SOL_SOCKET, SO_NOSIGPIPE, &isQuiet, socklen_t(MemoryLayout<Int32>.size))
        #endif
    }

    /// Accept one waiting connection.
    ///
    /// - Parameter descriptor: The listening descriptor.
    /// - Returns: The connection's descriptor, non-blocking, or nil when none waits.
    static func acceptWaiting(_ descriptor: Int32) -> Int32? {
        let accepted = accept(descriptor, nil, nil)
        guard accepted >= 0 else { return nil }
        prepare(accepted)
        return accepted
    }

    /// Read what a connection has.
    ///
    /// - Parameter descriptor: The connection.
    /// - Returns: The bytes; empty at the end of the stream; nil when nothing is there yet.
    /// - Throws: `ClientError.refused` with `forward_failed {detail}` when the connection broke.
    static func readAvailable(_ descriptor: Int32) throws -> Data? {
        var buffer = [UInt8](repeating: 0, count: Forward.bufferBytes)
        let count = buffer.withUnsafeMutableBytes { recv(descriptor, $0.baseAddress, $0.count, 0) }
        if count > 0 { return Data(buffer[0..<count]) }
        if count == 0 { return Data() }
        if errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR { return nil }
        throw failure("read")
    }

    /// Write as much of some bytes as the connection takes now.
    ///
    /// - Parameters:
    ///   - descriptor: The connection.
    ///   - bytes: The bytes.
    /// - Returns: How many were written; 0 when the connection takes none now.
    /// - Throws: `ClientError.refused` with `forward_failed {detail}` when the connection broke.
    static func writeAvailable(_ descriptor: Int32, _ bytes: Data) throws -> Int {
        let count = bytes.withUnsafeBytes { send(descriptor, $0.baseAddress, $0.count, sendFlags) }
        if count >= 0 { return count }
        if errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR { return 0 }
        throw failure("write")
    }

    /// Close a descriptor.
    ///
    /// - Parameter descriptor: The descriptor.
    static func closeDescriptor(_ descriptor: Int32) {
        close(descriptor)
    }

    private static func boundPort(_ descriptor: Int32) -> Int {
        var address = sockaddr_in()
        var length = socklen_t(MemoryLayout<sockaddr_in>.size)
        let read = withUnsafeMutablePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { getsockname(descriptor, $0, &length) }
        }
        return read == 0 ? Int(UInt16(bigEndian: address.sin_port)) : 0
    }

    private static func canBind(family: Int32, type: Int32, port: Int, isReused: Bool, isFamilyRequired: Bool)
        -> Bool
    {
        let descriptor = socket(family, type, 0)
        guard descriptor >= 0 else { return !isFamilyRequired }
        defer { close(descriptor) }
        var reuse: Int32 = isReused ? 1 : 0
        setsockopt(descriptor, SOL_SOCKET, SO_REUSEADDR, &reuse, socklen_t(MemoryLayout<Int32>.size))
        let bound: Int32
        if family == AF_INET6 {
            var address = sockaddr_in6()
            address.sin6_family = sa_family_t(AF_INET6)
            address.sin6_port = in_port_t(UInt16(port).bigEndian)
            address.sin6_addr = in6addr_any
            #if canImport(Darwin)
                address.sin6_len = UInt8(MemoryLayout<sockaddr_in6>.size)
            #endif
            bound = withUnsafePointer(to: &address) { pointer in
                pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                    bind(descriptor, $0, socklen_t(MemoryLayout<sockaddr_in6>.size))
                }
            }
        } else {
            var address = sockaddr_in()
            address.sin_family = sa_family_t(AF_INET)
            address.sin_port = in_port_t(UInt16(port).bigEndian)
            address.sin_addr = in_addr(s_addr: 0)
            #if canImport(Darwin)
                address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
            #endif
            bound = withUnsafePointer(to: &address) { pointer in
                pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                    bind(descriptor, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
                }
            }
        }
        if bound == 0 { return true }
        return errno == EADDRINUSE || errno == EACCES ? false : !isFamilyRequired
    }

    private static func loopback(port: Int) -> sockaddr_in {
        var address = sockaddr_in()
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = in_port_t(UInt16(clamping: port).bigEndian)
        address.sin_addr = in_addr(s_addr: inet_addr(Forward.bindHost))
        #if canImport(Darwin)
            address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        #endif
        return address
    }

    private static func setNonBlocking(_ descriptor: Int32) {
        let flags = fcntl(descriptor, F_GETFL, 0)
        _ = fcntl(descriptor, F_SETFL, flags | O_NONBLOCK)
    }

    /// The stream socket type, as each system's headers spell it.
    static var streamType: Int32 {
        #if canImport(Darwin)
            return SOCK_STREAM
        #else
            return Int32(SOCK_STREAM.rawValue)
        #endif
    }

    private static var datagramType: Int32 {
        #if canImport(Darwin)
            return SOCK_DGRAM
        #else
            return Int32(SOCK_DGRAM.rawValue)
        #endif
    }

    private static var sendFlags: Int32 {
        #if canImport(Darwin)
            return 0
        #else
            return Int32(MSG_NOSIGNAL)
        #endif
    }

    private static func failure(_ call: String) -> ClientError {
        .refusal("forward_failed", ["detail": "\(call): \(String(cString: strerror(errno)))"])
    }
}
