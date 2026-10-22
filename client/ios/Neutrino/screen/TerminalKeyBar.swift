import SwiftUI

/// The key row at the foot of the terminal's card, shown with the keyboard and without it until the status line's
/// Keys hides it: Esc, Tab, Ctrl, Shift, Alt and the four arrows; a modifier shows pressed while it is held for the
/// next key.
struct TerminalKeyBar: View {
    /// The modifiers held.
    @ObservedObject var keys: TerminalKeyState

    /// What a press on a key does.
    let onKey: (TerminalKey) -> Void

    @Environment(\.palette) private var palette

    var body: some View {
        if keys.isRowShown {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) {
                    ForEach(TerminalKey.allCases, id: \.self) { key in
                        keyButton(key, isHeld: keys.modifiers.isHeld(key))
                    }
                }
                .padding(8)
            }
            .background(palette.elevated)
        }
    }

    private func keyButton(_ key: TerminalKey, isHeld: Bool) -> some View {
        Button {
            onKey(key)
        } label: {
            Text(key.label)
                .font(.system(size: 13, design: .monospaced))
                .foregroundColor(isHeld ? palette.accent : palette.text)
                .padding(.horizontal, 12)
                .frame(minHeight: 34)
                .background(RoundedRectangle(cornerRadius: 6).fill(isHeld ? palette.accentWash : palette.surface))
                .overlay(
                    RoundedRectangle(cornerRadius: 6).stroke(
                        isHeld ? palette.accent : palette.borderStrong, lineWidth: 1))
        }
        .buttonStyle(.plain)
    }
}
