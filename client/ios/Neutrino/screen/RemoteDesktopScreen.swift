import SwiftUI

/// The desktops the machines of the joined hubs share, each with Configure and Connect: Connect shows the job while
/// the seat password comes from the hub and the entry's forward is made, then the viewer opens on the forward.
/// Configure keeps the codec and the quality the next Connect asks for. A Mac's entry carries a standing hint that a
/// black picture or a mouse that does nothing means RustDesk lacks its permissions there.
struct RemoteDesktopScreen: View {
    @ObservedObject var core: ClientCore

    @Environment(\.words) private var words
    @State private var configuring: ServiceListItem?

    var body: some View {
        ServiceList(hubs: core.hubs, type: "rdp", emptyKey: "ui.empty_desktops") { hub, entry, hasDivider in
            row(hub, entry, hasDivider: hasDivider)
        }
        .sheet(item: $configuring) { item in
            RemoteDesktopDialog(core: core, item: item)
        }
    }

    @ViewBuilder
    private func row(_ hub: HubView, _ entry: ChannelServiceEntry, hasDivider: Bool) -> some View {
        let key = RemoteDesktopSessions.key(hub.binding.id, entry.id)
        let isBusy = core.desktopsConnecting.contains(key)
        let reason = self.reason(hub, entry)
        FeatureRow(marker: EntryText.tone(hub, entry, isBusy: isBusy), hasDivider: hasDivider) {
            RowText(text: entry.title, style: .title)
            if core.viewing?.key == key {
                RowText(text: words.word("ui.rdp_open"), style: .note)
            }
            RowText(text: Self.address(entry), style: .mono)
            RowText(
                text: EntryText.provider(hub, entry, fallbackHost: entry.payload.text("host"), words: words),
                style: .note)
            if Self.hasMacHint(entry) {
                RowText(text: words.word("ui.rdp_mac_hint"), style: .note)
            }
            if let error = core.desktopErrors[key] {
                RowText(text: words.refusal(error), style: .error)
            }
            if let reason {
                RowText(text: reason, style: .reason)
            }
        } actions: {
            NeutrinoButton(
                label: words.word("ui.configure"), isEnabled: !entry.isUnhealthy && !hub.jobs.isRefreshing
            ) {
                configuring = ServiceListItem(hub: hub, entry: entry)
            }
            NeutrinoButton(
                label: words.word(isBusy ? "ui.job.connecting" : "ui.rdp_connect"), isBusy: isBusy,
                isEnabled: reason == nil && !hub.jobs.isRefreshing
            ) { core.connectDesktop(bindingId: hub.binding.id, entry: entry) }
        }
    }

    private func reason(_ hub: HubView, _ entry: ChannelServiceEntry) -> String? {
        if hub.isDisabled { return words.word("ui.reason.disabled") }
        if entry.isUnhealthy { return words.word("ui.reason.unhealthy") }
        if core.viewing != nil { return words.word("ui.reason_viewer_open") }
        return nil
    }

    /// Whether a desktop entry carries the standing Mac hint under its provider line.
    ///
    /// - Parameter entry: The desktop entry.
    /// - Returns: True when the sharing machine is a Mac.
    static func hasMacHint(_ entry: ChannelServiceEntry) -> Bool {
        entry.payload.text("platform_os") == RemoteDesktop.platformOsDarwin
    }

    /// The row's mono line: where the desktop is on the hub's networks, which the viewer never dials.
    ///
    /// - Parameter entry: The desktop entry.
    /// - Returns: The entry's `host:port`.
    static func address(_ entry: ChannelServiceEntry) -> String {
        "\(entry.payload.text("host")):\(entry.payload.number("port").map(String.init) ?? "")"
    }
}
