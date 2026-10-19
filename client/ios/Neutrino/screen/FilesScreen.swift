import SwiftUI

/// The shares the joined hubs publish, one row each: the share's name, `//host/share`, and who provides it.
struct FilesScreen: View {
    @ObservedObject var core: ClientCore

    @Environment(\.words) private var words

    var body: some View {
        ServiceList(hubs: core.hubs, type: "file", emptyKey: "ui.empty_files") { hub, entry, hasDivider in
            let host = entry.payload.text("host")
            FeatureRow(marker: EntryText.tone(hub, entry, isBusy: false), hasDivider: hasDivider) {
                RowText(text: entry.title, style: .title)
                if entry.isUnhealthy {
                    RowText(text: words.word("ui.unhealthy"), style: .note)
                }
                RowText(text: "//\(host)/\(entry.payload.text("share"))", style: .mono)
                RowText(text: EntryText.provider(hub, entry, fallbackHost: host, words: words), style: .note)
            } actions: {
                EmptyView()
            }
        }
    }
}
