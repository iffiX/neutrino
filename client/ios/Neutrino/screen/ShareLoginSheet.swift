import SwiftUI

/// The login sheet of a share the first Open shows: the user name, a picker over the share's users when it names
/// several and a field otherwise, the password, Remember, then Cancel and Connect. Connect logs in; the sheet
/// closes once the share page opens, and a refusal is worded under the fields.
struct ShareLoginSheet: View {
    @ObservedObject var core: ClientCore

    /// The share.
    let target: ShareTarget

    @Environment(\.words) private var words
    @Environment(\.palette) private var palette
    @Environment(\.dismiss) private var dismiss
    @State private var user = ""
    @State private var password = ""
    @State private var isKept = true
    @State private var isLoaded = false

    var body: some View {
        let row = core.shareRows[target.id] ?? ShareRow()
        let isReady = !user.isEmpty && !password.isEmpty && !row.isOpening
        VStack(alignment: .leading, spacing: 16) {
            RowText(text: target.title, style: .title)
            if target.users.count > 1 {
                MenuPickerRow(
                    label: words.word("ui.username_hint"), options: target.users, name: { $0 }, selection: $user)
            } else {
                RowText(text: words.word("ui.username_hint"), style: .note)
                field(TextField(words.word("ui.username_hint"), text: $user))
            }
            RowText(text: words.word("ui.password_hint"), style: .note)
            field(SecureField(words.word("ui.password_hint"), text: $password).onSubmit { connect(isReady) })
            Toggle(words.word("ui.remember"), isOn: $isKept)
                .font(.system(size: 14))
                .foregroundColor(palette.text)
                .tint(palette.accent)
            if let error = row.error {
                RowText(text: words.refusal(error), style: .error)
            }
            HStack(spacing: 8) {
                Spacer()
                NeutrinoButton(label: words.word("ui.cancel"), tier: .ghost, isEnabled: !row.isOpening) { dismiss() }
                NeutrinoButton(
                    label: words.word(row.isOpening ? "ui.job.connecting" : "ui.port_connect"), tier: .primary,
                    isBusy: row.isOpening, isEnabled: isReady
                ) { connect(isReady) }
            }
            Spacer()
        }
        .padding(16)
        .background(KeyboardClosingLayer())
        .background(palette.bg.ignoresSafeArea())
        .presentationDetents([.medium, .large])
        .onAppear(perform: load)
        .onChange(of: core.share?.target.id) { opened in
            if opened == target.id { dismiss() }
        }
    }

    private func field<Field: View>(_ field: Field) -> some View {
        field
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()
            .font(.system(size: 14, design: .monospaced))
            .padding(10)
            .background(RoundedRectangle(cornerRadius: 6).fill(palette.elevated))
            .overlay(RoundedRectangle(cornerRadius: 6).stroke(palette.border, lineWidth: 1))
    }

    private func load() {
        guard !isLoaded else { return }
        isLoaded = true
        user = target.users.first ?? ""
    }

    private func connect(_ isReady: Bool) {
        guard isReady else { return }
        core.shares.logIn(target, login: ShareLogin(user: user, password: password), isKept: isKept)
    }
}
