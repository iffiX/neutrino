import SwiftUI

/// The Terminals page: a card of machine chips, the account picker where the picked machine enables two or more
/// accounts, and New terminal after them in both layouts, then the
/// terminal's card with the tab strip, the terminal, the status line with Keyboard, Keys and the two switches, and
/// the key row, in one scrolling column. The terminal's card is as tall as the page, so the chips scroll away above
/// it; while the keyboard slides the page is kept at its end, so the key row moves with the keyboard's top.
/// A tap on empty space closes the keyboard.
struct TerminalScreen: View {
    @ObservedObject var core: ClientCore

    /// The views of every tab.
    let cache: TerminalViewCache

    @Environment(\.words) private var words
    @Environment(\.palette) private var palette

    var body: some View {
        let machines = core.hubs.filter(\.isConnected).flatMap { hub in
            hub.terminals.map { TerminalChip(hub: hub, machine: $0) }
        }
        let picked = machines.first { $0.ref == core.pickedMachine }
        GeometryReader { page in
            ScrollView {
                VStack(spacing: 12) {
                    if core.hubs.isEmpty {
                        SurfaceCard {
                            FeatureRow {
                                RowText(text: words.word("ui.services_wait_join"))
                            } actions: {
                                EmptyView()
                            }
                        }
                    } else {
                        machinesCard(machines, picked: picked)
                        if core.terminalTabs.isEmpty {
                            SurfaceCard {
                                FeatureRow {
                                    RowText(text: words.word("ui.terminal_none"))
                                    RowText(text: words.word("ui.terminal_pick_hint"), style: .reason)
                                } actions: {
                                    EmptyView()
                                }
                            }
                        } else {
                            terminalCard
                                .frame(height: max(Double(page.size.height) - 24, TerminalPage.cardMinHeight))
                        }
                    }
                }
                .padding(12)
                .frame(minHeight: page.size.height, alignment: .top)
                .background(KeyboardClosingLayer())
                .background(ScrollEndKeeper(keyboard: cache.keyboard))
            }
        }
        .onAppear { cache.paint(palette) }
        .onChange(of: palette.isDark) { _ in cache.paint(palette) }
        .onChange(of: reattachKey) { _ in reattach() }
        .onChange(of: core.terminalTabs.map(\.sessionId)) { ids in cache.keep(Set(ids)) }
    }

    private var activeTab: TerminalTab? {
        core.terminalTabs.first { $0.sessionId == core.activeTab }
    }

    private var reattachKey: String {
        guard let tab = activeTab else { return "" }
        let isHubUp = core.hubs.contains { $0.binding.id == tab.bindingId && $0.isConnected }
        return "\(tab.sessionId)/\(tab.phase)/\(isHubUp)"
    }

    private func pressKeyboard() {
        if cache.focus.isKeyboardShown {
            KeyboardClosingLayer.close()
        } else if let tab = activeTab {
            cache.openKeyboard(on: tab.sessionId)
        }
    }

    private func reattach() {
        guard let tab = activeTab, tab.phase == .detached,
            core.hubs.contains(where: { $0.binding.id == tab.bindingId && $0.isConnected })
        else { return }
        core.tabs.reattach(tab.sessionId)
    }

    private func machinesCard(_ machines: [TerminalChip], picked: TerminalChip?) -> some View {
        SurfaceCard {
            VStack(alignment: .leading, spacing: 8) {
                if machines.isEmpty {
                    RowText(text: words.word("ui.empty_terminals"))
                } else {
                    FlowRow {
                        ForEach(machines) { chip in machineChip(chip, isOn: chip.ref == picked?.ref) }
                        NeutrinoButton(
                            label: words.word("ui.terminal_new"), systemImage: "terminal", tier: .primary,
                            isEnabled: picked?.machine.isOnline == true && picked?.machine.accounts.isEmpty == false
                        ) {
                            core.newTerminal()
                        }
                    }
                    if let picked, picked.machine.accounts.count > 1 {
                        MenuPickerRow(
                            label: words.word("ui.terminal.account"), options: picked.machine.accounts, name: { $0 },
                            selection: Binding(
                                get: { Self.account(core.pickedAccount, of: picked.machine) },
                                set: { core.pickAccount($0) }))
                    }
                }
                if let picked {
                    RowText(
                        text: words.word(
                            "ui.machine_provided_by", ["hub": picked.hub.binding.title, "device": picked.machine.name]),
                        style: .note)
                }
                if picked == nil {
                    RowText(text: words.word("ui.reason.no_machine"), style: .reason)
                } else if picked?.machine.isOnline == false {
                    RowText(text: words.word("ui.reason.offline"), style: .reason)
                } else if picked?.machine.accounts.isEmpty == true {
                    RowText(text: words.word("ui.reason.terminal_no_account"), style: .reason)
                }
            }
            .padding(12)
        }
    }

    /// The account a new terminal runs as on a machine: the one picked while the machine enables it, else its first.
    ///
    /// - Parameters:
    ///   - picked: The account picked, empty for none.
    ///   - machine: The machine.
    /// - Returns: The account, empty when the machine enables none.
    static func account(_ picked: String, of machine: ChannelTerminal) -> String {
        machine.accounts.contains(picked) ? picked : machine.accounts.first ?? ""
    }

    private func machineChip(_ chip: TerminalChip, isOn: Bool) -> some View {
        Button {
            core.pickMachine(chip.ref)
        } label: {
            HStack(spacing: 8) {
                StatusDot(tone: chip.machine.isOnline ? .ok : .off)
                Text(chip.machine.name).font(.system(size: 12)).foregroundColor(isOn ? palette.ok : palette.text)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .overlay(Capsule().stroke(isOn ? palette.ok.opacity(0.6) : palette.border, lineWidth: 1))
        }
        .buttonStyle(.plain)
    }

    private var terminalCard: some View {
        VStack(spacing: 0) {
            TerminalTabStrip(core: core)
                .contentShape(Rectangle())
                .onTapGesture { KeyboardClosingLayer.close() }
            ZStack {
                palette.bg
                if let tab = activeTab {
                    TerminalViewRepresentable(cache: cache, sessionId: tab.sessionId)
                    if core.clearingTabs.contains(tab.sessionId) {
                        RowText(text: words.word("ui.job.clearing"), style: .note)
                    }
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 6))
            .padding(8)
            TerminalStatusLine(core: core, tab: activeTab, focus: cache.focus, keys: cache.keys) { pressKeyboard() }
            TerminalKeyBar(keys: cache.keys) { key in cache.press(key, on: activeTab?.sessionId ?? "") }
        }
        .background(KeyboardClosingLayer())
        .background(RoundedRectangle(cornerRadius: 12).fill(palette.surface))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(palette.border, lineWidth: 1))
    }
}
