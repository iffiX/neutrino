import XCTest

@testable import Neutrino

final class TerminalSessionMergeTests: XCTestCase {
    private let owned = ChannelTerminalSession(
        sessionId: "s1", title: "zsh", owner: "client:b1", ownerName: "", isOwned: true, isPersistent: true,
        isShared: false, attachedCount: 1)

    private func hub(
        _ connection: HubConnection, _ sessions: [ChannelTerminalSession] = [], isOnline: Bool = true
    ) -> HubView {
        var hub = HubView(binding: Samples.binding)
        hub.connection = connection
        hub.terminals = [ChannelTerminal(deviceId: "d1", name: "Argon", isOnline: isOnline, sessions: sessions)]
        return hub
    }

    private func merge(_ tabs: [TerminalTab], _ hubs: [HubView]) -> [TerminalTab] {
        let (listings, listedHubs, offline) = TerminalSessionMerge.listed(hubs)
        return TerminalSessionMerge.merge(
            tabs, listings: listings, listedHubs: listedHubs, offline: offline, dismissed: [])
    }

    func testATabWhoseMachineIsOfflineWaitsAndIsJudgedOnceItIsBack() {
        let before = merge([], [hub(.connected, [owned])])
        let offline = merge(before, [hub(.connected, isOnline: false)])
        XCTAssertEqual(before, offline)
        let back = merge(offline, [hub(.connected, [owned])])
        XCTAssertEqual(back.first?.phase, .detached)
        XCTAssertEqual(back.first?.isPersistent, true)
        let gone = merge(offline, [hub(.connected)])
        XCTAssertEqual(gone.first?.phase, .ended)
    }

    func testATabsShellAttachesAgainOnlyWhileItsMachineIsOnline() {
        let tab = TerminalTab(sessionId: "s1", bindingId: "b1", deviceId: "d1", name: "Argon", phase: .detached)
        XCTAssertTrue(TerminalSessionMerge.isMachineOnline([hub(.connected)], tab: tab))
        XCTAssertFalse(TerminalSessionMerge.isMachineOnline([hub(.connected, isOnline: false)], tab: tab))
        XCTAssertFalse(TerminalSessionMerge.isMachineOnline([hub(.waiting)], tab: tab))
        let other = TerminalTab(sessionId: "s1", bindingId: "b2", deviceId: "d1", name: "Argon", phase: .detached)
        XCTAssertFalse(TerminalSessionMerge.isMachineOnline([hub(.connected)], tab: other))
    }
}
