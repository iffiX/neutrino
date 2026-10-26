import Foundation

/// The parts of a web entry's address its local address keeps: its scheme, its port and its path with its query.
struct ForwardWebTarget: Equatable {
    /// `http` or `https`.
    let scheme: String

    /// The port the address names, else its scheme's.
    let port: Int

    /// The path, `/` when the address names none, with the address's query after it.
    let path: String

    /// Read a web entry's address.
    ///
    /// - Parameter url: The address.
    /// - Returns: The parts, or nil for an address that is not `http` or `https` or names no host.
    init?(_ url: String) {
        guard let parts = URLComponents(string: url), let scheme = parts.scheme?.lowercased(),
            scheme == "http" || scheme == "https", let host = parts.host, !host.isEmpty
        else { return nil }
        self.scheme = scheme
        port = parts.port ?? (scheme == "https" ? Channel.httpsDefaultPort : Channel.httpDefaultPort)
        let query = parts.percentEncodedQuery.map { "?" + $0 } ?? ""
        path = (parts.percentEncodedPath.isEmpty ? "/" : parts.percentEncodedPath) + query
    }
}
