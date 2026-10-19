import Foundation

/// The parts of a hub's address, `https://host:port`, an IPv6 host written in brackets.
enum ChannelAddress {
    /// The host of an address.
    ///
    /// - Parameter url: The address.
    /// - Returns: The host without brackets, or empty when the address does not read.
    static func host(of url: String) -> String {
        guard let host = URLComponents(string: url)?.host else { return "" }
        return host.trimmingCharacters(in: CharacterSet(charactersIn: "[]"))
    }

    /// The port of an address.
    ///
    /// - Parameter url: The address.
    /// - Returns: The port it names, else its scheme's, or nil when the address does not read.
    static func port(of url: String) -> Int? {
        guard let parts = URLComponents(string: url), let scheme = parts.scheme?.lowercased() else { return nil }
        if let port = parts.port { return port }
        return scheme == "https" ? Channel.httpsDefaultPort : Channel.httpDefaultPort
    }

    /// A host as an address writes it.
    ///
    /// - Parameter host: The host.
    /// - Returns: An IPv6 address in brackets, any other host as it is.
    static func bracketed(_ host: String) -> String {
        host.contains(":") ? "[\(host)]" : host
    }

    /// The same address with another host.
    ///
    /// - Parameters:
    ///   - url: The address.
    ///   - host: The new host.
    /// - Returns: `<scheme>://<host>:<port>`, or empty when the address does not read.
    static func url(_ url: String, onHost host: String) -> String {
        guard let parts = URLComponents(string: url), let scheme = parts.scheme, let port = port(of: url) else {
            return ""
        }
        return "\(scheme)://\(bracketed(host)):\(port)"
    }
}
