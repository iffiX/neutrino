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

    /// An entry's mono line under its app: its local address, or its kind alone while it has no number, and the
    /// health word while the hub reports it unhealthy.
    ///
    /// - Parameters:
    ///   - entry: The entry.
    ///   - port: The local port it listens on.
    ///   - words: The catalog.
    /// - Returns: The line.
    static func line(_ entry: ChannelServiceEntry, port: Int, words: WordCatalog) -> String {
        let address = port > 0 ? localAddress(entry, port: port) : words.word("ui.entry_kind.\(entry.type)")
        return entry.isUnhealthy ? "\(address) · \(words.word("ui.unhealthy"))" : address
    }

    /// An entry's kind as the Configure dialog names it: `ui.entry_kind.<type>`, with `/udp` after a UDP port.
    ///
    /// - Parameters:
    ///   - entry: The entry.
    ///   - words: The catalog.
    /// - Returns: The kind.
    static func kind(_ entry: ChannelServiceEntry, words: WordCatalog) -> String {
        let kind = words.word("ui.entry_kind.\(entry.type)")
        return entry.protocol == Forward.protocolUdp ? kind + "/udp" : kind
    }

    /// Which hub and which machine an app is on, and who answers for it: `ui.app_provided_by`, the machine being
    /// the host its first entry points at when the hub names none.
    ///
    /// - Parameters:
    ///   - hub: The hub that publishes the app.
    ///   - app: The app.
    ///   - entries: The app's entries.
    ///   - words: The catalog.
    /// - Returns: The line.
    static func provider(_ hub: HubView, _ app: ChannelApp, _ entries: [ChannelServiceEntry], words: WordCatalog)
        -> String
    {
        let source = sources.contains(app.source) ? words.word("ui.app_source.\(app.source)") : ""
        let machine = app.deviceName.isEmpty ? entries.first.map(host) ?? "" : app.deviceName
        return words.word("ui.app_provided_by", ["hub": hub.binding.title, "machine": machine, "source": source])
    }

    /// The sources an app's provider line words, as the hub names them.
    static let sources = ["module", "declared", "manual"]

    private static func host(_ entry: ChannelServiceEntry) -> String {
        let url = entry.payload.text("url")
        return url.isEmpty ? entry.payload.text("host") : ChannelAddress.host(of: url)
    }

    /// Why an app's buttons are disabled.
    ///
    /// - Parameters:
    ///   - hub: The hub that publishes the app.
    ///   - entries: The app's entries.
    ///   - row: The app's row.
    ///   - hasPage: Whether the app has an `http` or `https` entry, which Open opens.
    /// - Returns: `ui.reason.disabled` while the hub switched this phone off, `ui.reason.disconnect_first` for
    ///   Configure while the app is in use, `ui.reason.unhealthy` for Use while no entry is reachable,
    ///   `ui.reason.use_first` for Open while the app is not in use, else nil.
    static func reasonKey(_ hub: HubView, _ entries: [ChannelServiceEntry], _ row: ForwardRow, hasPage: Bool)
        -> String?
    {
        if hub.isDisabled { return "ui.reason.disabled" }
        if row.isInUse { return "ui.reason.disconnect_first" }
        if !entries.contains(where: { !$0.isUnhealthy }) { return "ui.reason.unhealthy" }
        if hasPage { return "ui.reason.use_first" }
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
