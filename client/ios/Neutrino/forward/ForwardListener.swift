import Foundation

/// One listener the transport holds for an entry or the panel.
struct ForwardListener: Equatable {
    /// The hub whose session carries its streams.
    let bindingId: String

    /// The row it shows on: `<binding>/<app>`, or `<binding>/#panel`.
    let appKey: String

    /// The loopback number.
    let port: Int

    /// `tcp` or `udp`.
    let `protocol`: String

    /// Its streams' `open` record.
    let open: [String: JSONValue]
}
