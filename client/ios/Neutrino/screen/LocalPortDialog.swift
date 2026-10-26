import SwiftUI

/// An app's Configure dialog: one line per entry, its name, its kind and a number field that starts at the
/// entry's number, the person's or else the hub's, then Cancel and Save. A number of the person's, from 1024 to
/// 65535, replaces the hub's on this phone alone, and an empty field goes back to the hub's; a refused number is
/// worded under the fields.
struct LocalPortDialog: View {
    @ObservedObject var core: ClientCore

    /// The app.
    let target: LocalPortTarget

    @Environment(\.words) private var words
    @Environment(\.palette) private var palette
    @Environment(\.dismiss) private var dismiss
    @State private var typed: [String: String] = [:]
    @State private var refusal: ClientError?
    @State private var isLoaded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            RowText(text: words.word("ui.app.port_dialog_title", ["app": target.title]), style: .title)
            ForEach(target.entries) { entry in
                HStack(spacing: 8) {
                    VStack(alignment: .leading, spacing: 2) {
                        RowText(text: entry.name.isEmpty ? entry.title : entry.name, style: .body)
                        RowText(text: AppText.kind(entry), style: .mono)
                    }
                    Spacer()
                    TextField(
                        "\(entry.localPort)",
                        text: Binding(get: { typed[entry.id] ?? "" }, set: { typed[entry.id] = Self.digits($0) })
                    )
                    .keyboardType(.numberPad)
                    .font(.system(size: 14, design: .monospaced))
                    .frame(maxWidth: 120)
                    .padding(10)
                    .background(RoundedRectangle(cornerRadius: 6).fill(palette.elevated))
                    .overlay(RoundedRectangle(cornerRadius: 6).stroke(palette.border, lineWidth: 1))
                }
            }
            if let refusal {
                RowText(text: words.word("ui.reason.\(refusal.code)", refusal.wordParams), style: .error)
            } else if let key = Self.reasonKey(Array(typed.values)) {
                RowText(text: words.word(key), style: .reason)
            }
            HStack(spacing: 8) {
                Spacer()
                NeutrinoButton(label: words.word("ui.cancel"), tier: .ghost) { dismiss() }
                NeutrinoButton(
                    label: words.word("ui.save"), tier: .primary,
                    isEnabled: Self.reasonKey(Array(typed.values)) == nil
                ) { save() }
            }
            Spacer()
        }
        .padding(16)
        .background(KeyboardClosingLayer())
        .background(palette.bg.ignoresSafeArea())
        .presentationDetents([.medium, .large])
        .onAppear(perform: load)
    }

    /// Why Save is disabled.
    ///
    /// - Parameter typed: Each entry's field as typed.
    /// - Returns: `ui.reason.port_range` while a field holds a number outside 1024 to 65535, else nil; an empty
    ///   field is the hub's number.
    static func reasonKey(_ typed: [String]) -> String? {
        let isOut = typed.contains { text in
            guard !text.isEmpty else { return false }
            guard let number = Int(text) else { return true }
            return !Forward.fixedPorts.contains(number)
        }
        return isOut ? "ui.reason.port_range" : nil
    }

    /// The numbers Save keeps: a field holding the hub's number, or nothing, goes back to the hub's.
    ///
    /// - Parameters:
    ///   - entries: The app's entries.
    ///   - typed: Each entry's field as typed.
    /// - Returns: Each entry's number by entry id, nil for the hub's.
    static func numbers(_ entries: [ChannelServiceEntry], typed: [String: String]) -> [String: Int?] {
        Dictionary(
            uniqueKeysWithValues: entries.map { entry in
                let number = typed[entry.id].flatMap { Int($0) }
                return (entry.id, number == entry.localPort ? nil : number)
            })
    }

    private static func digits(_ text: String) -> String {
        String(text.filter(\.isNumber).prefix(5))
    }

    private func load() {
        guard !isLoaded else { return }
        isLoaded = true
        let numbers = core.appNumbers(bindingId: target.bindingId, entries: target.entries)
        for entry in target.entries {
            typed[entry.id] = "\((numbers[entry.id] ?? nil) ?? entry.localPort)"
        }
    }

    private func save() {
        do {
            try core.configureApp(
                bindingId: target.bindingId, appId: target.appId, numbers: Self.numbers(target.entries, typed: typed))
            dismiss()
        } catch let error as ClientError {
            refusal = error
        } catch {
            refusal = .refusal(Channel.codeClientInternal, ["error": "\(error)"])
        }
    }
}
