import Foundation

/// The way a candidate address reaches a hub, known before its hello, with the rank a round on a connected hub
/// compares: `lan`, then `direct`, then the virtual networks, then the servers in between.
enum ChannelPath: String {
    /// An address inside a network this phone holds an address in.
    case lan
    /// Any other address of the hub's.
    case direct
    /// The hub's address on its NetBird network.
    case netbird
    /// The hub's address on its EasyTier network.
    case easytier
    /// The SSH relay's address the hub's state names.
    case sshRelay = "ssh_relay"
    /// SakuraFrp's address the hub's state names.
    case sakurafrp
    /// OpenFrp's address the hub's state names.
    case openfrp

    /// The path's place, 1 the best.
    var rank: Int {
        switch self {
        case .lan: return 1
        case .direct: return 2
        case .netbird, .easytier: return 3
        case .sshRelay, .sakurafrp, .openfrp: return 4
        }
    }

    /// The path of one candidate address.
    ///
    /// - Parameters:
    ///   - url: The address, `https://host:port`.
    ///   - overlays: The hub's virtual networks, whose hub address is that engine's path.
    ///   - serverPaths: The SSH relay's, SakuraFrp's and OpenFrp's addresses from the hub's last state.
    ///   - localNetworks: The networks this phone holds an address in.
    /// - Returns: The engine for the hub's address on a virtual network, the server's path for its address,
    ///   `lan` inside a local network, else `direct`.
    static func of(
        url: String, overlays: [ChannelOverlay], serverPaths: [String: ChannelPath],
        localNetworks: [ChannelLocalNetwork]
    ) -> ChannelPath {
        let host = ChannelAddress.host(of: url)
        if !host.isEmpty, let overlay = overlays.first(where: { $0.hubAddress == host }) {
            return ChannelPath(rawValue: overlay.provider) ?? .direct
        }
        if let path = serverPaths[url] { return path }
        if let address = ChannelLocalNetwork.bytes(of: host), localNetworks.contains(where: { $0.holds(address) }) {
            return .lan
        }
        return .direct
    }
}
