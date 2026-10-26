import SwiftUI

/// The apps the joined hubs publish, one row each: the title, the hub, the machine and the source, and one mono line
/// per `web` and `port` entry with its fixed local address, the `ssh` entries left out on a phone. Use
/// forwards every entry and opens the in-app browser at the first `http` or `https` entry, Configure opens the
/// local port dialog while the app is not in use, and Stop ends the app's forwards while it is.
struct AppsScreen: View {
    @ObservedObject var core: ClientCore

    @Environment(\.words) private var words
    @State private var configuring: LocalPortTarget?

    var body: some View {
        let apps = core.hubs.filter(\.isConnected).flatMap { hub in
            hub.apps.filter { !AppForwards.entries(of: hub, app: $0).isEmpty }.map { (hub, $0) }
        }
        let down = core.hubs.filter { !$0.isConnected }
        ScrollView {
            VStack(spacing: 16) {
                SurfaceCard {
                    if core.hubs.isEmpty {
                        sentence(words.word("ui.services_wait_join"))
                    } else if apps.isEmpty {
                        sentence(words.word("ui.empty_apps"))
                    } else {
                        ForEach(Array(apps.enumerated()), id: \.element.1.id) { index, item in
                            row(item.0, item.1, hasDivider: index < apps.count - 1)
                        }
                    }
                }
                if !down.isEmpty {
                    SurfaceCard {
                        ForEach(Array(down.enumerated()), id: \.element.id) { index, hub in
                            FeatureRow(marker: HubRowText.tone(hub), hasDivider: index < down.count - 1) {
                                RowText(text: hub.binding.title, style: .title)
                                RowText(
                                    text: HubRowText.stateWord(hub, words: words, now: Date().timeIntervalSince1970),
                                    style: .note)
                            } actions: {
                                EmptyView()
                            }
                            .opacity(0.6)
                        }
                    }
                }
            }
            .padding(16)
        }
        .sheet(item: $configuring) { target in
            LocalPortDialog(core: core, target: target)
        }
    }

    private func sentence(_ text: String) -> some View {
        FeatureRow {
            RowText(text: text)
        } actions: {
            EmptyView()
        }
    }

    @ViewBuilder
    private func row(_ hub: HubView, _ app: ChannelApp, hasDivider: Bool) -> some View {
        let entries = AppForwards.entries(of: hub, app: app)
        let row = core.forwardRows[AppForwards.key(hub.binding.id, app.id)] ?? ForwardRow()
        let isFree = row.job == nil && !hub.jobs.isRefreshing
        let isUsable = entries.contains { !$0.isUnhealthy }
        FeatureRow(marker: AppText.tone(hub, entries, isBusy: row.job != nil), hasDivider: hasDivider) {
            RowText(text: app.title, style: .title)
            RowText(text: AppText.provider(hub, app, entries, words: words), style: .note)
            ForEach(entries) { entry in
                RowText(
                    text: AppText.line(
                        entry, port: core.localPort(bindingId: hub.binding.id, entry: entry), words: words),
                    style: .mono)
            }
            if let error = row.error {
                RowText(text: words.refusal(error), style: .error)
            }
            if isFree, let key = AppText.reasonKey(hub, entries, row) {
                RowText(text: words.word(key), style: .reason)
            }
        } actions: {
            NeutrinoButton(
                label: words.word(row.job == .opening ? ForwardJob.opening.rawValue : "ui.app.use"),
                tier: .primary, isBusy: row.job == .opening, isEnabled: isFree && isUsable && !hub.isDisabled
            ) { core.useApp(bindingId: hub.binding.id, app: app) }
            NeutrinoButton(label: words.word("ui.app.configure"), isEnabled: isFree && !row.isInUse) {
                configuring = LocalPortTarget(
                    bindingId: hub.binding.id, appId: app.id, title: app.title, entries: entries)
            }
            if row.isInUse {
                NeutrinoButton(
                    label: words.word(row.job == .disconnecting ? ForwardJob.disconnecting.rawValue : "ui.app.stop"),
                    tier: row.job == nil ? .danger : .plain, isBusy: row.job == .disconnecting,
                    isEnabled: row.job == nil
                ) { core.stopApp(bindingId: hub.binding.id, appId: app.id) }
            }
        }
    }
}
