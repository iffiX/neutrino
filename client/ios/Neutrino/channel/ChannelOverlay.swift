import Foundation

/// One of a hub's virtual networks, as far as this app uses it: which engine runs it, and the hub's
/// address on it, which every round dials. The app joins no virtual network itself.
struct ChannelOverlay: Codable, Equatable {
    /// `netbird` or `easytier`.
    let provider: String

    /// The hub's own address on the network, without its prefix length; empty when the hub knows none.
    let hubAddress: String

    private enum CodingKeys: String, CodingKey {
        case provider
        case hubAddress = "hub_address"
    }

    /// Read one overlay object tolerantly.
    ///
    /// - Parameter value: The object as the link or the state carried it.
    /// - Returns: The overlay, or nil for an object of no known provider.
    static func of(_ value: JSONValue) -> ChannelOverlay? {
        guard let object = value.objectValue else { return nil }
        let provider = object.text("provider")
        guard provider == Channel.providerNetbird || provider == Channel.providerEasytier else { return nil }
        return ChannelOverlay(provider: provider, hubAddress: object.text("hub_address"))
    }

    /// Every overlay of a list a phone reads, in the hub's order.
    ///
    /// - Parameter value: A JSON array of overlay objects.
    /// - Returns: The ones of a known provider.
    static func list(_ value: JSONValue?) -> [ChannelOverlay] {
        (value?.arrayValue ?? []).compactMap { of($0) }
    }
}
