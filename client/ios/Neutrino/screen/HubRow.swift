import SwiftUI

/// One hub's row: its dot, its title and tags, its state line, its address, and Panel, Reconnect and Leave.
struct HubRow: View {
    @ObservedObject var core: ClientCore

    /// The hub.
    let hub: HubView

    /// Whether a rule parts it from the row under it.
    let hasDivider: Bool

    @Environment(\.words) private var words

    var body: some View {
        let id = hub.binding.id
        FeatureRow(marker: HubRowText.tone(hub), hasDivider: hasDivider) {
            let tags = HubRowText.tags(hub, words: words)
            HStack(spacing: 8) {
                RowText(text: hub.binding.title, style: .title)
                ForEach(tags, id: \.self) { Badge(text: $0) }
            }
            if tags.isEmpty {
                TimelineView(.periodic(from: .now, by: 1)) { context in
                    RowText(
                        text: HubRowText.stateLine(hub, words: words, now: context.date.timeIntervalSince1970),
                        style: .note)
                }
            }
            RowText(text: monoLine, style: .mono)
            if let error = hub.jobError {
                RowText(text: words.refusal(error), style: .error)
            }
            if hub.isDisabled {
                RowText(text: words.word("ui.reason.disabled"), style: .reason)
            }
        } actions: {
            if hub.isPanelAllowed && !hub.isLeaveOnly {
                NeutrinoButton(
                    label: words.word(hub.jobs.isOpeningPanel ? "ui.job.opening" : "ui.hub_panel"),
                    isBusy: hub.jobs.isOpeningPanel,
                    isEnabled: hub.isConnected && !hub.jobs.isLeaving
                ) { core.openPanel(id) }
            }
            if hub.waitReason == .replaced {
                NeutrinoButton(label: words.word("ui.reconnect")) { core.reconnect(id) }
            }
            ArmedButton(
                key: "leave-\(id)",
                label: words.word(hub.jobs.isLeaving ? "ui.job.leaving" : "ui.leave"),
                armedLabel: words.word("ui.leave_armed"),
                isBusy: hub.jobs.isLeaving
            ) { core.leave(id) }
        }
    }

    private var monoLine: String {
        let address = hub.connectedAddress.isEmpty ? hub.binding.gatewayUrl : hub.connectedAddress
        guard !hub.software.isEmpty else { return address }
        return address + " · " + words.word("ui.hub_software", ["software": hub.software])
    }
}
