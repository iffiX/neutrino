import SwiftUI

/// The web services the joined hubs publish. Open forwards the entry to this phone's loopback through the hub
/// when it has no forward, reads a fresh token for an entry with `is_token_required`, and opens the in-app
/// browser on the loopback, the button showing the job meanwhile. Configure opens the local port dialog while
/// the entry is not forwarded; a forwarded row names its loopback address and has Disconnect.
struct WebScreen: View {
    @ObservedObject var core: ClientCore

    @Environment(\.words) private var words
    @State private var configuring: LocalPortTarget?

    var body: some View {
        ServiceList(hubs: core.hubs, type: "web", emptyKey: "ui.empty_web") { hub, entry, hasDivider in
            row(hub, entry, hasDivider: hasDivider)
        }
        .sheet(item: $configuring) { target in
            LocalPortDialog(core: core, target: target)
        }
    }

    @ViewBuilder
    private func row(_ hub: HubView, _ entry: ChannelServiceEntry, hasDivider: Bool) -> some View {
        let url = entry.payload.text("url")
        let row = core.forwardRows[WebForwards.key(hub.binding.id, entry.id)] ?? ForwardRow()
        let isFree = row.job == nil && !hub.jobs.isRefreshing && !hub.isDisabled
        FeatureRow(marker: EntryText.tone(hub, entry, isBusy: row.job != nil), hasDivider: hasDivider) {
            RowText(text: entry.title, style: .title)
            if entry.isUnhealthy {
                RowText(text: words.word("ui.unhealthy"), style: .note)
            }
            RowText(
                text: url
                    + (row.isForwarded ? " → " + words.word("ui.forwarding_to", ["port": "\(row.localPort)"]) : ""),
                style: .mono)
            RowText(
                text: EntryText.provider(hub, entry, fallbackHost: ChannelAddress.host(of: url), words: words),
                style: .note)
            if let error = row.error {
                RowText(text: words.refusal(error), style: .error)
            }
            if let reason = reason(hub, entry, row) {
                RowText(text: reason, style: .reason)
            }
        } actions: {
            NeutrinoButton(label: words.word("ui.configure"), isEnabled: isFree && !row.isForwarded) {
                configuring = LocalPortTarget(bindingId: hub.binding.id, entryId: entry.id, title: entry.title)
            }
            NeutrinoButton(
                label: words.word(row.job == .opening ? ForwardJob.opening.rawValue : "ui.open"),
                isBusy: row.job == .opening, isEnabled: !entry.isUnhealthy && isFree
            ) { core.openWeb(bindingId: hub.binding.id, entry: entry) }
            if row.isForwarded {
                NeutrinoButton(
                    label: words.word(
                        row.job == .disconnecting ? ForwardJob.disconnecting.rawValue : "ui.port_disconnect"),
                    tier: row.job == nil ? .danger : .plain, isBusy: row.job == .disconnecting,
                    isEnabled: row.job == nil && !hub.jobs.isRefreshing
                ) { core.disconnectWeb(bindingId: hub.binding.id, entryId: entry.id) }
            }
        }
    }

    private func reason(_ hub: HubView, _ entry: ChannelServiceEntry, _ row: ForwardRow) -> String? {
        if row.job != nil || hub.jobs.isRefreshing { return nil }
        if hub.isDisabled { return words.word("ui.reason.disabled") }
        if entry.isUnhealthy { return words.word("ui.reason.unhealthy") }
        if row.isForwarded { return words.word("ui.reason.disconnect_first") }
        return nil
    }
}
