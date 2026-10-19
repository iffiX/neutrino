import SwiftUI

/// The Settings page: the About card, then the Language and Theme pickers with Save and Cancel.
struct SettingsScreen: View {
    @ObservedObject var core: ClientCore

    @Environment(\.words) private var words
    @Environment(\.palette) private var palette
    @Environment(\.openURL) private var openURL
    @State private var draft: ClientSettings?

    var body: some View {
        let saved = core.settings
        let current = draft ?? saved
        ScrollView {
            VStack(spacing: 16) {
                SurfaceCard { about }
                SurfaceCard {
                    VStack(alignment: .leading, spacing: 14) {
                        RowText(text: words.word("ui.settings_title"), style: .title)
                        pickerRow(words.word("ui.language"), selection: binding(\.language, current)) {
                            ForEach(Client.languages, id: \.self) { Text(words.word("ui.language_name.\($0)")).tag($0) }
                        }
                        pickerRow(words.word("ui.theme"), selection: binding(\.theme, current)) {
                            ForEach(Client.themes, id: \.self) { Text(words.word("ui.theme_name.\($0)")).tag($0) }
                        }
                        HStack(spacing: 8) {
                            Spacer()
                            NeutrinoButton(label: words.word("ui.cancel"), tier: .ghost, isEnabled: current != saved) {
                                draft = nil
                            }
                            NeutrinoButton(label: words.word("ui.save"), tier: .primary, isEnabled: current != saved) {
                                core.save(current)
                                draft = nil
                            }
                        }
                    }
                    .padding(16)
                }
            }
            .padding(16)
        }
    }

    private var about: some View {
        VStack(alignment: .leading, spacing: 10) {
            RowText(text: words.word("ui.about"), style: .title)
            sectionLabel(words.word("ui.about_this_machine"))
            valueRow(words.word("ui.about_machine"), core.machine.hostname)
            valueRow(words.word("ui.about_platform"), "iOS \(core.machine.osVersion)")
            sectionLabel(words.word("ui.about_carried"))
            creditRow(
                "Neutrino client \(core.machine.version)", licence: Client.licence,
                source: Client.sourceUrls[core.edition] ?? Client.sourceUrls[Client.editionIntl] ?? "")
            creditRow(
                "\(Client.swiftTermName) \(Client.swiftTermVersion)", licence: Client.swiftTermLicence,
                source: Client.swiftTermSourceUrl)
        }
        .padding(16)
    }

    private func sectionLabel(_ text: String) -> some View {
        Text(text.uppercased())
            .font(.system(size: 11, weight: .semibold))
            .foregroundColor(palette.textMuted)
            .padding(.top, 6)
    }

    private func valueRow(_ label: String, _ value: String) -> some View {
        HStack {
            Text(label).font(.system(size: 13)).foregroundColor(palette.textMuted)
            Spacer()
            Text(value).font(.system(size: 13, design: .monospaced)).foregroundColor(palette.text)
        }
    }

    private func creditRow(_ name: String, licence: String, source: String) -> some View {
        HStack {
            Text(name).font(.system(size: 13)).foregroundColor(palette.textMuted)
            Spacer()
            Text("\(licence) — ").font(.system(size: 13, design: .monospaced)).foregroundColor(palette.text)
            Button(words.word("ui.about_source_link")) {
                if let url = URL(string: source) { openURL(url) }
            }
            .font(.system(size: 13))
            .foregroundColor(palette.accent)
        }
    }

    private func pickerRow<Options: View>(
        _ label: String, selection: Binding<String>, @ViewBuilder options: () -> Options
    ) -> some View {
        HStack {
            Text(label).font(.system(size: 14)).foregroundColor(palette.text)
            Spacer()
            Picker(label, selection: selection, content: options).pickerStyle(.menu).tint(palette.accent)
        }
    }

    private func binding(_ field: WritableKeyPath<ClientSettings, String>, _ current: ClientSettings) -> Binding<String>
    {
        Binding(
            get: { current[keyPath: field] },
            set: { value in
                var next = draft ?? core.settings
                next[keyPath: field] = value
                draft = next
            })
    }
}
