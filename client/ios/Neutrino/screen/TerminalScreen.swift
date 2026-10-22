import SwiftUI

/// The Terminals page: a card of machine chips, then the terminal's card with the tab strip, the terminal and
/// the status line with the two switches, in one scrolling column. The terminal's card is as tall as the page,
/// so the chips scroll away above it and the key row sits above the keyboard.
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
                            terminalCard.frame(height: max(page.size.height - 24, 200))
                        }
                    }
                }
                .padding(12)
            }
        }
        .preference(
            key: PageActionKey.self,
            value: PageAction(
                label: words.word("ui.terminal_new"), systemImage: "terminal",
                isEnabled: picked?.machine.isOnline == true
            ) { core.newTerminal() }
        )
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
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 8) {
                            ForEach(machines) { chip in machineChip(chip, isOn: chip.ref == picked?.ref) }
                        }
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
                }
            }
            .padding(12)
        }
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
            TerminalStatusLine(core: core, tab: activeTab)
        }
        .background(RoundedRectangle(cornerRadius: 12).fill(palette.surface))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(palette.border, lineWidth: 1))
    }
}
