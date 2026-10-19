import Foundation

#if canImport(Darwin)
    import Darwin
#else
    import Glibc
#endif

/// A network this phone holds an address in.
struct ChannelLocalNetwork: Equatable {
    /// This phone's address there: four bytes for IPv4, sixteen for IPv6.
    let address: [UInt8]

    /// The network's prefix length.
    let prefix: Int

    /// Whether an address lies inside this network.
    ///
    /// - Parameter host: The address's bytes.
    /// - Returns: True when both are of one family and share the first `prefix` bits.
    func holds(_ host: [UInt8]) -> Bool {
        guard host.count == address.count, prefix >= 0 else { return false }
        let bits = min(prefix, address.count * 8)
        for index in 0..<bits {
            let mask = UInt8(0x80) >> UInt8(index % 8)
            if address[index / 8] & mask != host[index / 8] & mask { return false }
        }
        return true
    }

    /// The bytes of a literal address.
    ///
    /// - Parameter host: An IPv4 or IPv6 address, without brackets.
    /// - Returns: Its four or sixteen bytes, or nil for a name or something that does not read.
    static func bytes(of host: String) -> [UInt8]? {
        var v4 = in_addr()
        if inet_pton(AF_INET, host, &v4) == 1 {
            return withUnsafeBytes(of: &v4) { Array($0) }
        }
        var v6 = in6_addr()
        if inet_pton(AF_INET6, host, &v6) == 1 {
            return withUnsafeBytes(of: &v6) { Array($0) }
        }
        return nil
    }

    /// The networks the phone's interfaces that are up hold an address in, loopback aside.
    ///
    /// - Returns: Each interface address with its prefix length; empty when the interfaces cannot be read.
    static func deviceNetworks() -> [ChannelLocalNetwork] {
        var first: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&first) == 0 else { return [] }
        defer { freeifaddrs(first) }
        var networks: [ChannelLocalNetwork] = []
        var cursor = first
        while let entry = cursor {
            cursor = entry.pointee.ifa_next
            let flags = Int32(truncatingIfNeeded: entry.pointee.ifa_flags)
            guard flags & Int32(truncatingIfNeeded: IFF_UP) != 0, flags & Int32(truncatingIfNeeded: IFF_LOOPBACK) == 0,
                let family = entry.pointee.ifa_addr.map({ Int32($0.pointee.sa_family) }),
                let address = bytes(of: entry.pointee.ifa_addr, family: family),
                let mask = bytes(of: entry.pointee.ifa_netmask, family: family)
            else { continue }
            let prefix = mask.reduce(0) { $0 + $1.nonzeroBitCount }
            networks.append(ChannelLocalNetwork(address: address, prefix: prefix))
        }
        return networks
    }

    private static func bytes(of socketAddress: UnsafeMutablePointer<sockaddr>?, family: Int32) -> [UInt8]? {
        guard let socketAddress else { return nil }
        switch family {
        case AF_INET:
            return socketAddress.withMemoryRebound(to: sockaddr_in.self, capacity: 1) { pointer in
                var value = pointer.pointee.sin_addr
                return withUnsafeBytes(of: &value) { Array($0) }
            }
        case AF_INET6:
            return socketAddress.withMemoryRebound(to: sockaddr_in6.self, capacity: 1) { pointer in
                var value = pointer.pointee.sin6_addr
                return withUnsafeBytes(of: &value) { Array($0) }
            }
        default:
            return nil
        }
    }
}
