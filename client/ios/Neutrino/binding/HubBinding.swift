import Foundation

/// What this phone keeps of one hub it joined, in the desktop client's binding shape.
struct HubBinding: Codable, Equatable {
    /// The key this phone keeps the binding under: the id the join returned, or, for a binding kept before its
    /// ticket was spent, an id made here.
    var id: String

    /// The name this phone joined under.
    var name: String = ""

    /// The hub's id from its welcome.
    var hubId: String = ""

    /// The hub's name from its welcome.
    var hubName: String = ""

    /// The address that last answered.
    var gatewayUrl: String

    /// Every address the hub answers on, from the link and then each state.
    var gatewayUrls: [String] = []

    /// The pinned SHA-256 of the hub's certificate.
    var fingerprint: String

    /// The secret every hello carries; empty while the ticket is unspent.
    var token: String

    /// The link's ticket while it is unspent; empty once the join is done.
    var ticket: String = ""

    /// The id the hub gave a binding whose ticket was spent after it was kept; empty when `id` is the hub's own.
    var hubBindingId: String = ""

    /// The hub's virtual networks, preferred first.
    var overlays: [ChannelOverlay] = []

    private enum CodingKeys: String, CodingKey {
        case id
        case name
        case hubId = "hub_id"
        case hubName = "hub_name"
        case gatewayUrl = "gateway_url"
        case gatewayUrls = "gateway_urls"
        case fingerprint
        case token
        case ticket
        case hubBindingId = "hub_binding_id"
        case overlays
    }

    /// Every address the binding holds: the hub's list, and the one that last answered when it is not in it.
    var storedUrls: [String] {
        if gatewayUrl.isEmpty || gatewayUrls.contains(gatewayUrl) { return gatewayUrls }
        return gatewayUrls + [gatewayUrl]
    }

    /// Whether the binding waits for its ticket to be spent: no hello goes before.
    var isPending: Bool { !ticket.isEmpty }

    /// The id the hub knows the binding by.
    var boundId: String { hubBindingId.isEmpty ? id : hubBindingId }

    /// The name a page shows: the hub's own, else its address.
    var title: String { hubName.isEmpty ? gatewayUrl : hubName }

    /// The hub's address on each of its virtual networks, as the round dials it: the stored address with that
    /// host, else the host at the port of the address that last answered.
    var overlayUrls: [(url: String, provider: String)] {
        overlays.compactMap { overlay in
            guard !overlay.hubAddress.isEmpty else { return nil }
            if let stored = storedUrls.first(where: { ChannelAddress.host(of: $0) == overlay.hubAddress }) {
                return (stored, overlay.provider)
            }
            let port = ChannelAddress.port(of: gatewayUrl) ?? Channel.httpsDefaultPort
            return ("https://" + ChannelAddress.bracketed(overlay.hubAddress) + ":\(port)", overlay.provider)
        }
    }

    /// The addresses one connection round dials, all at once.
    ///
    /// - Parameter nameUrl: The address the hub's name resolves to on this network, or empty.
    /// - Returns: The hub's address on each virtual network, the name's, then the stored ones, each once.
    func candidateUrls(nameUrl: String) -> [String] {
        var seen = Set<String>()
        return (overlayUrls.map(\.url) + [nameUrl] + storedUrls).filter { url in
            guard !url.isEmpty, !seen.contains(url) else { return false }
            seen.insert(url)
            return true
        }
    }
}

extension HubBinding {
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        name = try container.decodeIfPresent(String.self, forKey: .name) ?? ""
        hubId = try container.decodeIfPresent(String.self, forKey: .hubId) ?? ""
        hubName = try container.decodeIfPresent(String.self, forKey: .hubName) ?? ""
        gatewayUrl = try container.decode(String.self, forKey: .gatewayUrl)
        gatewayUrls = try container.decodeIfPresent([String].self, forKey: .gatewayUrls) ?? []
        fingerprint = try container.decode(String.self, forKey: .fingerprint)
        token = try container.decode(String.self, forKey: .token)
        ticket = try container.decodeIfPresent(String.self, forKey: .ticket) ?? ""
        hubBindingId = try container.decodeIfPresent(String.self, forKey: .hubBindingId) ?? ""
        overlays = try container.decodeIfPresent([ChannelOverlay].self, forKey: .overlays) ?? []
    }
}
