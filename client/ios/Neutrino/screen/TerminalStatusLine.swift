import SwiftUI

/// The terminal's status line: the shown tab's note, and the two switches at the right; a tab this phone does
/// not own shows both disabled and names who opened it.
struct TerminalStatusLine: View {
    @ObservedObject var core: ClientCore

    /// The tab shown, nil for none.
    let tab: TerminalTab?

    @Environment(\.words) private var words
    @Environment(\.palette) private var palette

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                if let tab, let note = tab.note {
                    RowText(text: words.refusal(note), style: .error)
                } else if let tab, tab.phase == .detached {
                    RowText(text: words.word("ui.terminal_detached"), style: .reason)
                }
                if let tab, !tab.isOwned {
                    RowText(text: words.word("ui.reason.not_owned", ["owner": tab.ownerLabel]), style: .reason)
                }
            }
            Spacer()
            switchView("ui.terminal_persistent", isOn: tab?.isPersistent ?? false) { isOn in
                guard let tab else { return }
                core.tabs.persist(tab.sessionId, isPersistent: isOn, isShared: tab.isShared)
            }
            switchView("ui.terminal_shared", isOn: tab?.isShared ?? false) { isOn in
                guard let tab else { return }
                core.tabs.persist(tab.sessionId, isPersistent: tab.isPersistent, isShared: isOn)
            }
        }
        .padding(.horizontal, 12)
        .padding(.bottom, 8)
    }

    private func switchView(_ key: String, isOn: Bool, onChange: @escaping (Bool) -> Void) -> some View {
        let isEnabled = tab?.canPersist ?? false
        return Toggle(isOn: Binding(get: { isOn }, set: onChange)) {
            Text(words.word(key)).font(.system(size: 12)).foregroundColor(isEnabled ? palette.text : palette.textMuted)
        }
        .toggleStyle(.switch)
        .tint(isEnabled ? palette.accent : palette.textFaint)
        .disabled(!isEnabled)
        .fixedSize()
    }
}
