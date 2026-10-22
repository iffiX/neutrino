import SwiftUI

/// The local port dialog of a web entry: **Auto**, or **Fixed** with a number from 1024 to 65535, then Save and
/// Cancel; a refused number is worded under the field.
struct LocalPortDialog: View {
    @ObservedObject var core: ClientCore

    /// The entry.
    let target: LocalPortTarget

    @Environment(\.words) private var words
    @Environment(\.palette) private var palette
    @Environment(\.dismiss) private var dismiss
    @State private var isFixed = false
    @State private var number = ""
    @State private var refusal: ClientError?
    @State private var isLoaded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            RowText(text: target.title, style: .title)
            RowText(text: words.word("ui.local_port"), style: .note)
            Picker(words.word("ui.local_port"), selection: $isFixed) {
                Text(words.word("ui.local_port_auto")).tag(false)
                Text(words.word("ui.local_port_fixed")).tag(true)
            }
            .pickerStyle(.segmented)
            if isFixed {
                TextField("20000", text: $number)
                    .keyboardType(.numberPad)
                    .font(.system(size: 14, design: .monospaced))
                    .padding(10)
                    .background(RoundedRectangle(cornerRadius: 6).fill(palette.elevated))
                    .overlay(RoundedRectangle(cornerRadius: 6).stroke(palette.border, lineWidth: 1))
            }
            if let refusal {
                RowText(text: words.word("ui.reason.\(refusal.code)", refusal.wordParams), style: .error)
            }
            HStack(spacing: 8) {
                Spacer()
                NeutrinoButton(label: words.word("ui.cancel"), tier: .ghost) { dismiss() }
                NeutrinoButton(label: words.word("ui.save"), tier: .primary) { save() }
            }
            Spacer()
        }
        .padding(16)
        .background(KeyboardClosingLayer())
        .background(palette.bg.ignoresSafeArea())
        .presentationDetents([.medium])
        .onAppear(perform: load)
    }

    private func load() {
        guard !isLoaded else { return }
        isLoaded = true
        let choice = core.localPort(bindingId: target.bindingId, entryId: target.entryId)
        isFixed = choice.isFixed
        number = choice.port == 0 ? "" : "\(choice.port)"
    }

    private func save() {
        let choice = LocalPortChoice(isFixed: isFixed, port: isFixed ? Int(number) ?? 0 : 0)
        do {
            try core.configureLocalPort(bindingId: target.bindingId, entryId: target.entryId, choice: choice)
            dismiss()
        } catch let error as ClientError {
            refusal = error
        } catch {
            refusal = .refusal(Channel.codeClientInternal, ["error": "\(error)"])
        }
    }
}
