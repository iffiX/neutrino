import Foundation

#if canImport(Darwin)
    import Darwin
#else
    import Glibc
#endif

/// The address `hub.neutrino.internal` resolves to on the network the phone stands on.
enum HubNameResolver {
    /// Resolve the hub's name to an IPv4 address, off the main queue.
    ///
    /// - Parameter completion: Called on the main queue with the address, or nil when the name does not resolve.
    static func resolve(_ completion: @escaping (String?) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            let address = firstIPv4(of: Channel.hubName)
            DispatchQueue.main.async { completion(address) }
        }
    }

    private static func firstIPv4(of name: String) -> String? {
        var hints = addrinfo()
        hints.ai_family = AF_INET
        var first: UnsafeMutablePointer<addrinfo>?
        guard getaddrinfo(name, nil, &hints, &first) == 0, let entry = first else { return nil }
        defer { freeaddrinfo(first) }
        guard let socketAddress = entry.pointee.ai_addr else { return nil }
        return socketAddress.withMemoryRebound(to: sockaddr_in.self, capacity: 1) { pointer -> String? in
            var address = pointer.pointee.sin_addr
            var text = [CChar](repeating: 0, count: Int(INET_ADDRSTRLEN))
            guard inet_ntop(AF_INET, &address, &text, socklen_t(INET_ADDRSTRLEN)) != nil else { return nil }
            return String(decoding: text.prefix { $0 != 0 }.map { UInt8(bitPattern: $0) }, as: UTF8.self)
        }
    }
}
