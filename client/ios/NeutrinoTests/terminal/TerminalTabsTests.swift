import XCTest

@testable import Neutrino

final class TerminalTabsTests: XCTestCase {
    private let transport = FakeTransport()
    private let clock = FakeClientClock()
    private var replays: [String] = []
    private var hub: FakeTerminalHub?

    override func setUp() {
        _ = try? transport.start(directory: "/data", secret: String(repeating: "ee", count: 32))
        replays = []
        hub = FakeTerminalHub(transport: transport)
    }

    private func makeTabs() -> TerminalTabs {
        let tabs = TerminalTabs(hubOf: { [weak self] _ in self?.hub }, clock: clock)
        tabs.onReplay = { self.replays.append($0) }
        return tabs
    }

    private func end(_ index: Int) throws -> FakeTransportEnd {
        XCTAssertTrue(RunLoopWait.until { self.transport.streams.count > index })
        return try XCTUnwrap(transport.streams.dropFirst(index).first?.end)
    }

    private func data(_ end: FakeTransportEnd, _ text: String) {
        end.record(Transport.recordData, Data(text.utf8))
        RunLoopWait.turn()
    }

    private func detachedTab(_ tabs: TerminalTabs) throws -> String {
        let sessionId = tabs.create(bindingId: "b1", deviceId: "d1", name: "box")
        tabs.sized(sessionId, cols: 80, rows: 24)
        let first = try end(0)
        XCTAssertTrue(RunLoopWait.until { tabs.tabs.first?.phase == .open })
        tabs.persist(sessionId, isPersistent: true, isShared: false)
        data(first, "before")
        first.close()
        XCTAssertTrue(RunLoopWait.until { tabs.tabs.first?.phase == .detached })
        tabs.reattach(sessionId)
        _ = try end(1)
        XCTAssertEqual(transport.streams.count, 2)
        return sessionId
    }

    func testATabAttachingAgainKeepsItsOutputUntilTheReplaysFirstBytes() throws {
        let tabs = makeTabs()
        let sessionId = try detachedTab(tabs)
        XCTAssertEqual(replays, [])
        XCTAssertEqual(tabs.keptOutput(sessionId), Data("before".utf8))
        let second = try end(1)
        data(second, "again")
        XCTAssertEqual(replays, [sessionId])
        XCTAssertEqual(tabs.keptOutput(sessionId), Data("again".utf8))
        data(second, " and on")
        XCTAssertEqual(replays, [sessionId])
        XCTAssertEqual(tabs.keptOutput(sessionId), Data("again and on".utf8))
    }

    func testATabWhoseSessionIsGoneEndsWithItsLastOutput() throws {
        let tabs = makeTabs()
        let sessionId = try detachedTab(tabs)
        try end(1).refuse("session_unknown")
        XCTAssertTrue(RunLoopWait.until { tabs.tabs.first?.phase == .ended })
        XCTAssertEqual(replays, [])
        XCTAssertEqual(tabs.keptOutput(sessionId), Data("before".utf8))
    }

    func testATabOpensAShellStreamWithItsAccountAndSendsItsSizeAsAResizeRecord() throws {
        let tabs = makeTabs()
        let sessionId = tabs.create(bindingId: "b1", deviceId: "d1", name: "box", account: "iffi")
        tabs.sized(sessionId, cols: 80, rows: 24)
        let open = try XCTUnwrap(try end(0).isClosed ? nil : transport.streams.first?.open)
        XCTAssertEqual(open.text("kind"), "shell")
        XCTAssertEqual(open.text("account"), "iffi")
        XCTAssertEqual(open.text("session_id"), sessionId)
        tabs.sized(sessionId, cols: 100, rows: 30)
        let stream = try end(0)
        XCTAssertTrue(RunLoopWait.until { stream.records.contains { $0.type == Transport.recordResize } })
        let resize = try XCTUnwrap(stream.records.first { $0.type == Transport.recordResize })
        let size = try XCTUnwrap(JSONValue.parse(resize.payload).objectValue)
        XCTAssertEqual(size["cols"], .int(100))
        XCTAssertEqual(size["rows"], .int(30))
    }

    private let hubEnds: [(HubWaitReason, String)] = [
        (.disabled, "ui.terminal.disabled"), (.unknownDevice, "ui.terminal.unknown_device"),
    ]

    private func hubView(_ reason: HubWaitReason?) -> HubView {
        var hub = HubView(binding: Samples.binding)
        hub.connection = reason == nil ? .connecting : .waiting
        hub.waitReason = reason
        return hub
    }

    private func openTab(
        _ tabs: TerminalTabs, isPersistent: Bool = false, isShared: Bool = false
    ) throws -> FakeTransportEnd {
        let index = transport.streams.count
        let sessionId = tabs.create(bindingId: "b1", deviceId: "d1", name: "box")
        tabs.sized(sessionId, cols: 80, rows: 24)
        let stream = try end(index)
        XCTAssertTrue(RunLoopWait.until { tabs.tabs.first?.phase == .open })
        if isPersistent || isShared { tabs.persist(sessionId, isPersistent: isPersistent, isShared: isShared) }
        return stream
    }

    func testAPlainTabEndsAtOnceWhenItsStreamDrops() throws {
        let tabs = makeTabs()
        try openTab(tabs).close()
        XCTAssertTrue(RunLoopWait.until { tabs.tabs.first?.phase == .ended })
        XCTAssertNil(tabs.tabs.first?.note)
        XCTAssertEqual(tabs.tabs.first?.statusKey, "ui.terminal.detached_ended")
        tabs.take([hubView(.hubSilent)])
        XCTAssertEqual(tabs.tabs.first?.statusKey, "ui.terminal.detached_ended")
        var connected = HubView(binding: Samples.binding)
        connected.connection = .connected
        tabs.take([connected])
        XCTAssertEqual(tabs.tabs.first?.phase, .ended)
        XCTAssertEqual(tabs.tabs.first?.statusKey, "ui.terminal.detached_ended")
    }

    func testAKeptTabsDroppedStreamWaitsForTheHubWithNoCode() throws {
        let tabs = makeTabs()
        try openTab(tabs, isPersistent: true).close()
        XCTAssertTrue(RunLoopWait.until { tabs.tabs.first?.phase == .detached })
        tabs.take([hubView(.hubSilent)])
        let tab = try XCTUnwrap(tabs.tabs.first)
        XCTAssertEqual(tab.phase, .detached)
        XCTAssertNil(tab.note)
        XCTAssertEqual(tab.statusKey, "ui.terminal.detached")
    }

    func testAPlainTabEndsWithTheHubsRefusalWhenItsStreamEndsFirst() throws {
        for (reason, key) in hubEnds {
            let tabs = makeTabs()
            try openTab(tabs).close()
            XCTAssertTrue(RunLoopWait.until { tabs.tabs.first?.phase == .ended })
            XCTAssertEqual(tabs.tabs.first?.statusKey, "ui.terminal.detached_ended")
            tabs.take([hubView(reason)])
            let tab = try XCTUnwrap(tabs.tabs.first)
            XCTAssertEqual(tab.phase, .ended)
            XCTAssertNil(tab.note)
            XCTAssertEqual(tab.statusKey, key)
            tabs.take([hubView(nil)])
            XCTAssertEqual(tabs.tabs.first?.statusKey, key)
        }
    }

    func testAPlainTabEndsWithTheHubsRefusalWhenTheHubsRowComesFirst() throws {
        for (reason, key) in hubEnds {
            let tabs = makeTabs()
            let stream = try openTab(tabs)
            tabs.take([hubView(reason)])
            XCTAssertEqual(tabs.tabs.first?.phase, .open)
            stream.close()
            XCTAssertTrue(RunLoopWait.until { tabs.tabs.first?.phase == .ended })
            XCTAssertEqual(tabs.tabs.first?.statusKey, key)
        }
    }

    func testAReattachWhileTheHubIsAwayWaitsWithNoCode() throws {
        let tabs = makeTabs()
        try openTab(tabs, isPersistent: true).close()
        XCTAssertTrue(RunLoopWait.until { tabs.tabs.first?.phase == .detached })
        hub = nil
        tabs.reattach(try XCTUnwrap(tabs.tabs.first?.sessionId))
        let tab = try XCTUnwrap(tabs.tabs.first)
        XCTAssertEqual(tab.phase, .detached)
        XCTAssertNil(tab.note)
        XCTAssertEqual(tab.statusKey, "ui.terminal.detached")
    }

    func testAKeptTabWaitsWhileItsHubHasThisClientSwitchedOff() throws {
        let tabs = makeTabs()
        try openTab(tabs, isPersistent: true).close()
        XCTAssertTrue(RunLoopWait.until { tabs.tabs.first?.phase == .detached })
        tabs.take([hubView(.disabled)])
        XCTAssertEqual(tabs.tabs.first?.phase, .detached)
        XCTAssertEqual(tabs.tabs.first?.statusKey, "ui.terminal.detached")
    }

    func testAKeptTabEndsSayingItsShellRunsWhenTheHubForgetsThisClient() throws {
        let running = "ui.terminal.unknown_device_running"
        let streamFirst = makeTabs()
        try openTab(streamFirst, isPersistent: true).close()
        XCTAssertTrue(RunLoopWait.until { streamFirst.tabs.first?.phase == .detached })
        streamFirst.take([hubView(.unknownDevice)])
        XCTAssertEqual(streamFirst.tabs.first?.phase, .ended)
        XCTAssertEqual(streamFirst.tabs.first?.statusKey, running)

        let rowFirst = makeTabs()
        let stream = try openTab(rowFirst, isShared: true)
        rowFirst.take([hubView(.unknownDevice)])
        XCTAssertEqual(rowFirst.tabs.first?.phase, .open)
        stream.close()
        XCTAssertTrue(RunLoopWait.until { rowFirst.tabs.first?.phase == .ended })
        XCTAssertEqual(rowFirst.tabs.first?.statusKey, running)
    }
}

/// One connected hub's terminal questions, its streams on a `FakeTransport`.
private final class FakeTerminalHub: TerminalHub {
    private let transport: FakeTransport

    init(transport: FakeTransport) {
        self.transport = transport
    }

    func openShell(_ open: [String: JSONValue]) -> Result<TransportStream, ClientError> {
        do {
            return .success(
                try TransportStream.open(
                    dialer: transport, secret: transport.secret, binding: "b1", open: open, carriage: .records))
        } catch let refusal as ClientError {
            return .failure(refusal)
        } catch {
            return .failure(.refusal(Channel.codeHubUnreachable))
        }
    }

    func persist(
        sessionId: String, isPersistent: Bool, isShared: Bool,
        completion: @escaping (Result<[String: JSONValue], ClientError>) -> Void
    ) {
        completion(.success([:]))
    }

    func stopSession(_ sessionId: String, completion: @escaping (Result<[String: JSONValue], ClientError>) -> Void) {
        completion(.success([:]))
    }
}
