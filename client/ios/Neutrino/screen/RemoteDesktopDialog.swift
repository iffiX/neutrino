import SwiftUI

/// The Configure sheet of a shared desktop: a Codec picker (Auto, then each codec the core offers) and a Quality
/// picker, then Cancel and Save; the next Connect asks for the choice.
struct RemoteDesktopDialog: View {
    @ObservedObject var core: ClientCore

    /// The entry, with its hub.
    let item: ServiceListItem

    @Environment(\.words) private var words
    @Environment(\.palette) private var palette
    @Environment(\.dismiss) private var dismiss
    @State private var codec = RemoteDesktopCodec.auto
    @State private var quality = RemoteDesktopQuality.balanced
    @State private var isLoaded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            RowText(text: words.word("ui.rdp_configure_title"), style: .title)
            RowText(text: item.entry.title, style: .note)
            MenuPickerRow(
                label: words.word("ui.rdp_codec"), options: RemoteDesktopCodec.allCases,
                name: { $0.title.isEmpty ? words.word("ui.rdp_codec_auto") : $0.title }, selection: $codec)
            MenuPickerRow(
                label: words.word("ui.rdp_quality"), options: RemoteDesktopQuality.allCases,
                name: { words.word($0.wordKey) }, selection: $quality)
            HStack(spacing: 8) {
                Spacer()
                NeutrinoButton(label: words.word("ui.cancel"), tier: .ghost) { dismiss() }
                NeutrinoButton(label: words.word("ui.save"), tier: .primary) {
                    core.configureDesktop(
                        bindingId: item.hub.binding.id, entryId: item.entry.id,
                        choice: RemoteDesktopChoice(codec: codec, quality: quality))
                    dismiss()
                }
            }
            Spacer()
        }
        .padding(16)
        .background(palette.bg.ignoresSafeArea())
        .presentationDetents([.medium])
        .onAppear(perform: load)
    }

    private func load() {
        guard !isLoaded else { return }
        isLoaded = true
        let choice = core.desktopChoice(bindingId: item.hub.binding.id, entryId: item.entry.id)
        codec = choice.codec
        quality = choice.quality
    }
}
