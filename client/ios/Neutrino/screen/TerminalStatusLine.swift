import SwiftUI

/// The terminal's status line: the Keyboard and Keys buttons at its left end, the two switches at the right, and
/// under them the shown tab's note; a tab this phone does not own shows both switches disabled and names who
/// opened it. A tap on its empty space closes the keyboard.
struct TerminalStatusLine: View {
    @ObservedObject var core: ClientCore

    /// The tab shown, nil for none.
    let tab: TerminalTab?

    /// The keyboard as the terminals follow it.
    @ObservedObject var focus: TerminalKeyboardFocus

    /// The key row.
    @ObservedObject var keys: TerminalKeyState

    /// What Keyboard does.
    let onKeyboard: () -> Void

    @Environment(\.words) private var words
    @Environment(\.palette) private var palette

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 8) {
                RoundButton(
                    systemImage: RemoteDesktopButton.keyboard.systemImage,
                    label: words.word(RemoteDesktopButton.keyboard.wordKey), size: 30, isActive: focus.isKeyboardShown,
                    action: onKeyboard)
                RoundButton(
                    systemImage: RemoteDesktopButton.keys.systemImage,
                    label: words.word(RemoteDesktopButton.keys.wordKey), size: 30, isActive: keys.isRowShown
                ) { keys.toggleRow() }
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
            if let tab, let note = tab.note {
                RowText(text: words.refusal(note), style: .error)
            } else if let tab, tab.phase == .detached {
                RowText(text: words.word("ui.terminal_detached"), style: .reason)
            }
            if let tab, !tab.isOwned {
                RowText(text: words.word("ui.reason.not_owned", ["owner": tab.ownerLabel]), style: .reason)
            }
        }
        .padding(.horizontal, 12)
        .padding(.bottom, 8)
        .background(KeyboardClosingLayer())
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
