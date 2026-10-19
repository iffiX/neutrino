import SwiftUI

/// The hubs this phone has joined, one row each with its state and its actions, then the row that opens the
/// Join page.
struct HubsScreen: View {
    @ObservedObject var core: ClientCore

    /// What pressing the join row does.
    let onJoin: () -> Void

    @Environment(\.words) private var words
    @Environment(\.palette) private var palette

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                SurfaceCard {
                    if core.hubs.isEmpty {
                        FeatureRow {
                            RowText(text: words.word("ui.no_hubs"))
                        } actions: {
                            EmptyView()
                        }
                    } else {
                        ForEach(Array(core.hubs.enumerated()), id: \.element.id) { index, hub in
                            HubRow(core: core, hub: hub, hasDivider: index < core.hubs.count - 1)
                        }
                    }
                }
                SurfaceCard {
                    Button(action: onJoin) {
                        FeatureRow {
                            RowText(text: words.word("ui.add_hub"), style: .title)
                            RowText(text: words.word("ui.join_hint"), style: .note)
                        } actions: {
                            Image(systemName: "chevron.right").foregroundColor(palette.textMuted)
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(16)
        }
    }
}
