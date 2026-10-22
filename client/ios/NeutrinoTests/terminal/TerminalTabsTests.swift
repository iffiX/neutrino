import XCTest

@testable import Neutrino

final class TerminalTabsTests: XCTestCase {
    private let socket = FakeChannelSocket(url: "wss://192.168.1.1:8443/channel")
    private let clock = FakeClientClock()
    private var streams: [ChannelStream] = []
    private var replays: [String] = []

    private func makeTabs() -> TerminalTabs {
        let tabs = TerminalTabs(
            open: { _, kind, _, _ in
                let stream = ChannelStream(
                    id: UInt32(self.streams.count * 2 + 1), kind: kind, socket: self.socket, hasBytes: true,
                    clock: self.clock, onClosedHere: { _ in })
                self.streams.append(stream)
                return .success(stream)
            }, clock: clock)
        tabs.onReplay = { self.replays.append($0) }
        return tabs
    }

    private func detachedTab(_ tabs: TerminalTabs) throws -> String {
        let sessionId = tabs.create(bindingId: "b1", deviceId: "d1", name: "box")
        tabs.sized(sessionId, cols: 80, rows: 24)
        let first = try XCTUnwrap(streams.first)
        first.takeBytes(Data("before".utf8))
        first.end()
        XCTAssertEqual(tabs.tabs.first?.phase, .detached)
        tabs.reattach(sessionId)
        XCTAssertEqual(streams.count, 2)
        return sessionId
    }

    func testATabAttachingAgainKeepsItsOutputUntilTheReplaysFirstBytes() throws {
        let tabs = makeTabs()
        let sessionId = try detachedTab(tabs)
        XCTAssertEqual(replays, [])
        XCTAssertEqual(tabs.keptOutput(sessionId), Data("before".utf8))
        streams[1].takeBytes(Data("again".utf8))
        XCTAssertEqual(replays, [sessionId])
        XCTAssertEqual(tabs.keptOutput(sessionId), Data("again".utf8))
        streams[1].takeBytes(Data(" and on".utf8))
        XCTAssertEqual(replays, [sessionId])
        XCTAssertEqual(tabs.keptOutput(sessionId), Data("again and on".utf8))
    }

    func testATabWhoseSessionIsGoneEndsWithItsLastOutput() throws {
        let tabs = makeTabs()
        let sessionId = try detachedTab(tabs)
        streams[1].takeClose(code: "session_unknown", params: [:])
        XCTAssertEqual(tabs.tabs.first?.phase, .ended)
        XCTAssertEqual(replays, [])
        XCTAssertEqual(tabs.keptOutput(sessionId), Data("before".utf8))
    }
}
