import Foundation

/// What a hub says is to be true for this phone: the `state` frame's sections.
struct ChannelClientState: Equatable {
    /// What the next report names back.
    let hash: String

    /// Whether the hub switched this client off.
    let isDisabled: Bool

    /// The published list, resolved for the address this session came from.
    let services: [ChannelServiceEntry]

    /// The apps the `web`, `port` and `ssh` entries belong to.
    var apps: [ChannelApp] = []

    /// Every address the hub answers the channel on.
    let urls: [String]

    /// The member of `urls` that is the SSH relay's address, empty while the relay adds none.
    let sshRelayUrl: String

    /// The member of `urls` that is SakuraFrp's address, empty while it adds none.
    let sakurafrpUrl: String

    /// The member of `urls` that is OpenFrp's address, empty while it adds none.
    let openfrpUrl: String

    /// The hub's virtual networks, preferred first.
    let overlays: [ChannelOverlay]

    /// The managed machines this phone may open a shell on.
    let terminals: [ChannelTerminal]

    /// Whether this phone may open the hub's panel through `connect {is_panel: true}`.
    let isPanelAllowed: Bool

    /// The way this phone's session reached the hub, as `reached_through` names it.
    let reachedThrough: String

    /// The path each server's address of the state stands for.
    var serverPaths: [String: ChannelPath] {
        var paths: [String: ChannelPath] = [:]
        for (url, path) in [(sshRelayUrl, ChannelPath.sshRelay), (sakurafrpUrl, .sakurafrp), (openfrpUrl, .openfrp)]
        where !url.isEmpty {
            paths[url] = path
        }
        return paths
    }

    /// Read a state frame tolerantly: a section that is absent takes its empty value.
    ///
    /// - Parameter frame: The frame.
    /// - Returns: The state.
    static func of(_ frame: [String: JSONValue]) -> ChannelClientState {
        ChannelClientState(
            hash: frame.text("hash"),
            isDisabled: frame.flag("is_disabled"),
            services: (frame["services"]?.arrayValue ?? []).compactMap { ChannelServiceEntry.of($0) },
            apps: (frame["apps"]?.arrayValue ?? []).compactMap { ChannelApp.of($0) },
            urls: EnrollmentLink.cleanUrls(frame["urls"]),
            sshRelayUrl: trimmed(frame.text("ssh_relay_url")),
            sakurafrpUrl: trimmed(frame.text("sakurafrp_url")),
            openfrpUrl: trimmed(frame.text("openfrp_url")),
            overlays: ChannelOverlay.list(frame["overlays"]),
            terminals: (frame["terminals"]?.arrayValue ?? []).compactMap { ChannelTerminal.of($0) },
            isPanelAllowed: frame.flag("is_panel_allowed"),
            reachedThrough: frame.text("reached_through"))
    }

    private static func trimmed(_ url: String) -> String {
        var text = url.trimmingCharacters(in: .whitespaces)
        while text.hasSuffix("/") { text.removeLast() }
        return text
    }
}
