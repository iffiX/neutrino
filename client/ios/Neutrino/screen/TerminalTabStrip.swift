import SwiftUI

/// The tab strip: a tab per session, its label, its badges and its ×; the active tab drawn as a selected chip.
struct TerminalTabStrip: View {
    @ObservedObject var core: ClientCore

    @Environment(\.words) private var words
    @Environment(\.palette) private var palette
    @EnvironmentObject private var arm: ArmState

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 4) {
                ForEach(Array(core.terminalTabs.enumerated()), id: \.element.id) { index, tab in
                    tabChip(tab, index: index)
                }
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 6)
        }
        .overlay(Rectangle().fill(palette.border).frame(height: 1), alignment: .bottom)
    }

    private func tabChip(_ tab: TerminalTab, index: Int) -> some View {
        let isActive = tab.sessionId == core.activeTab
        let name = tab.phase == .ended ? words.word("ui.terminal_ended") : "\(tab.name) · \(index + 1)"
        let armKey = "end-\(tab.sessionId)"
        let isArmed = arm.armed == armKey
        return HStack(spacing: 6) {
            Button {
                core.tabs.select(tab.sessionId)
            } label: {
                HStack(spacing: 6) {
                    Text(name)
                        .font(.system(size: 12, design: .monospaced))
                        .foregroundColor(isActive ? palette.accent : palette.text)
                        .lineLimit(1)
                    if tab.isPersistent { Badge(text: words.word("ui.badge.kept")) }
                    if tab.isShared { Badge(text: words.word("ui.badge.shared")) }
                    if tab.attachedCount > 1 { Badge(text: "\(tab.attachedCount)") }
                }
            }
            .buttonStyle(.plain)
            Button {
                if tab.isKept && tab.phase != .ended && !isArmed {
                    arm.arm(armKey)
                } else {
                    arm.disarm()
                    core.tabs.close(tab.sessionId)
                }
            } label: {
                Text(isArmed ? words.word("ui.terminal_end_armed") : "×")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundColor(isArmed ? palette.error : palette.textMuted)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(words.word("ui.terminal_close", ["name": name]))
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
        .background(RoundedRectangle(cornerRadius: 6).fill(isActive ? palette.elevated : .clear))
        .overlay(RoundedRectangle(cornerRadius: 6).stroke(isActive ? palette.accent : palette.border, lineWidth: 1))
    }
}
