import SwiftUI

/// A service page's body: every connected hub's entries of one type in one card, a row for each hub that is not
/// connected, and one sentence when there is nothing to show.
struct ServiceList<Row: View>: View {
    private let hubs: [HubView]
    private let type: String
    private let emptyKey: String
    private let row: (HubView, ChannelServiceEntry, Bool) -> Row

    @Environment(\.words) private var words

    /// List one type of entry.
    ///
    /// - Parameters:
    ///   - hubs: Every hub joined.
    ///   - type: The service type.
    ///   - emptyKey: The catalog key of the sentence for no entry.
    ///   - row: One entry's row, given its hub, the entry, and whether a divider follows it.
    init(
        hubs: [HubView], type: String, emptyKey: String,
        @ViewBuilder row: @escaping (HubView, ChannelServiceEntry, Bool) -> Row
    ) {
        self.hubs = hubs
        self.type = type
        self.emptyKey = emptyKey
        self.row = row
    }

    var body: some View {
        let entries = hubs.flatMap { hub in hub.services(of: type).map { ServiceListItem(hub: hub, entry: $0) } }
        let down = hubs.filter { !$0.isConnected }
        ScrollView {
            VStack(spacing: 16) {
                SurfaceCard {
                    if hubs.isEmpty {
                        FeatureRow {
                            RowText(text: words.word("ui.services_wait_join"))
                        } actions: {
                            EmptyView()
                        }
                    } else if entries.isEmpty {
                        FeatureRow {
                            RowText(text: words.word(emptyKey))
                        } actions: {
                            EmptyView()
                        }
                    } else {
                        ForEach(Array(entries.enumerated()), id: \.element.id) { index, item in
                            row(item.hub, item.entry, index < entries.count - 1)
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
    }
}
