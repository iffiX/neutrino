import SwiftUI

/// The shares the joined hubs publish, one row each: the share's name, `<share> (<account>)` for each account of a
/// folder share, `//host/share`, and who provides it. Open
/// on a machine's share logs in with the login the hub hands and asks nothing; on a declared share it logs in
/// with the login held, or shows the login sheet when none is, and Forget password arms and removes the login
/// held.
struct FilesScreen: View {
    @ObservedObject var core: ClientCore

    @Environment(\.words) private var words
    @State private var asking: ShareTarget?

    var body: some View {
        ServiceList(hubs: core.hubs, type: "file", emptyKey: "ui.empty_files") { hub, entry, hasDivider in
            row(hub, entry, hasDivider: hasDivider)
        }
        .sheet(item: $asking) { target in
            ShareLoginSheet(core: core, target: target)
        }
    }

    @ViewBuilder
    private func row(_ hub: HubView, _ entry: ChannelServiceEntry, hasDivider: Bool) -> some View {
        let host = entry.payload.text("host")
        let target = ShareTarget.of(hub, entry)
        let key = target?.id ?? ""
        let row = core.shareRows[key] ?? ShareRow()
        let isHeld = core.shareLogins.contains(key)
        let isDeclared = target?.isDeclared ?? false
        let isFree = !row.isOpening && !hub.jobs.isRefreshing && !hub.isDisabled
        FeatureRow(marker: EntryText.tone(hub, entry, isBusy: row.isOpening), hasDivider: hasDivider) {
            RowText(text: target?.title ?? entry.title, style: .title)
            if entry.isUnhealthy {
                RowText(text: words.word("ui.unhealthy"), style: .note)
            }
            RowText(text: "//\(host)/\(entry.payload.text("share"))", style: .mono)
            RowText(text: EntryText.provider(hub, entry, fallbackHost: host, words: words), style: .note)
            if let error = row.error {
                RowText(text: words.refusal(error), style: .error)
            }
            if let reason = reason(hub, entry, row) {
                RowText(text: reason, style: .reason)
            }
        } actions: {
            if let target {
                NeutrinoButton(
                    label: words.word(row.isOpening ? "ui.job.opening" : "ui.open"), isBusy: row.isOpening,
                    isEnabled: isFree && !entry.isUnhealthy
                ) {
                    if isHeld || !isDeclared { core.shares.open(target) } else { asking = target }
                }
                if isHeld && isDeclared {
                    ArmedButton(
                        key: "forget-\(key)", label: words.word("ui.forget_password"),
                        armedLabel: words.word("ui.forget_password_arm"), isEnabled: !row.isOpening
                    ) { core.shares.forgetLogin(key) }
                }
            }
        }
    }

    private func reason(_ hub: HubView, _ entry: ChannelServiceEntry, _ row: ShareRow) -> String? {
        if row.isOpening || hub.jobs.isRefreshing { return nil }
        if hub.isDisabled { return words.word("ui.reason.disabled") }
        if entry.isUnhealthy { return words.word("ui.reason.unhealthy") }
        return nil
    }
}
