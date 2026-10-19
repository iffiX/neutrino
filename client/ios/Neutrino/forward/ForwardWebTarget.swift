import Foundation

/// The parts of a web entry's address a forward opens: its scheme, its port and its path.
struct ForwardWebTarget: Equatable {
    /// `http` or `https`.
    let scheme: String

    /// The port the address names, else its scheme's.
    let port: Int

    /// The path, `/` when the address names none.
    let path: String

    /// Read a web entry's address.
    ///
    /// - Parameter url: The address.
    init?(_ url: String) {
        guard let parts = URLComponents(string: url), let scheme = parts.scheme?.lowercased(),
            let host = parts.host, !host.isEmpty
        else { return nil }
        self.scheme = scheme
        port = parts.port ?? (scheme == "https" ? Channel.httpsDefaultPort : Channel.httpDefaultPort)
        path = parts.percentEncodedPath.isEmpty ? "/" : parts.percentEncodedPath
    }
}
