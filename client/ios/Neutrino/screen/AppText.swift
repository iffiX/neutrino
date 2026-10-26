import Foundation

/// What an app's row says: its dot, its entries' local addresses and the reason its buttons are disabled.
enum AppText {
    /// An entry's local address as the Apps page shows it: `<scheme>://127.0.0.1:<port><path>` for a `web` entry,
    /// `127.0.0.1:<port>` for a `port` entry with `/udp` after a UDP one; on iOS every app opens on the loopback.
    ///
    /// - Parameters:
    ///   - entry: The entry.
    ///   - port: The local port it listens on.
    /// - Returns: The address.
    static func localAddress(_ entry: ChannelServiceEntry, port: Int) -> String {
        if entry.type == "web", let target = ForwardWebTarget(entry.payload.text("url")) {
            return "\(target.scheme)://\(Forward.bindHost):\(port)\(target.path)"
        }
        let address = "\(Forward.bindHost):\(port)"
        return entry.protocol == Forward.protocolUdp ? address + "/udp" : address
    }

    /// An entry's kind as the Apps page names it: `web`, `port`, or `port/udp` for a UDP port.
    ///
    /// - Parameter entry: The entry.
    /// - Returns: The kind.
    static func kind(_ entry: ChannelServiceEntry) -> String {
        entry.protocol == Forward.protocolUdp ? "\(entry.type)/udp" : entry.type
    }

    /// Why an app's buttons are disabled.
    ///
    /// - Parameters:
    ///   - hub: The hub that publishes the app.
    ///   - entries: The app's entries.
    ///   - row: The app's row.
    /// - Returns: `ui.reason.disabled` while the hub switched this phone off, `ui.reason.unhealthy` while no entry
    ///   is reachable, `ui.reason.disconnect_first` for Configure while the app is in use, else nil.
    static func reasonKey(_ hub: HubView, _ entries: [ChannelServiceEntry], _ row: ForwardRow) -> String? {
        if hub.isDisabled { return "ui.reason.disabled" }
        if !entries.contains(where: { !$0.isUnhealthy }) { return "ui.reason.unhealthy" }
        if row.isInUse { return "ui.reason.disconnect_first" }
        return nil
    }

    /// The dot of an app's row: pulsing while its hub refreshes or its own job runs, green while some entry is
    /// reachable, amber when none is.
    ///
    /// - Parameters:
    ///   - hub: The hub that publishes the app.
    ///   - entries: The app's entries.
    ///   - isBusy: Whether the app's own job runs.
    /// - Returns: The tone.
    static func tone(_ hub: HubView, _ entries: [ChannelServiceEntry], isBusy: Bool) -> DotTone {
        if isBusy || hub.jobs.isRefreshing { return .pulse }
        return entries.contains(where: { !$0.isUnhealthy }) ? .ok : .wait
    }
}
