import XCTest

@testable import Neutrino

final class RemoteDesktopSessionsTests: XCTestCase {
    private let socket = FakeChannelSocket(url: "https://192.168.1.1:8443")
    private let clock = FakeClientClock()
    private var registry: ChannelStreamRegistry?
    private var sessions: RemoteDesktopSessions?
    private var answers: [(Result<[String: JSONValue], ClientError>) -> Void] = []

    override func setUp() {
        answers = []
        let registry = ChannelStreamRegistry(socket: socket, clock: clock)
        self.registry = registry
        sessions = makeSessions(choiceOf: { _ in RemoteDesktopChoice() })
    }

    override func tearDown() {
        sessions?.forget(bindingId: "b1")
        sessions?.forget(bindingId: "b2")
        turnMainQueue()
    }

    private func makeSessions(choiceOf: @escaping (String) -> RemoteDesktopChoice) -> RemoteDesktopSessions? {
        guard let registry else { return nil }
        return RemoteDesktopSessions(
            material: { [weak self] _, _, completion in self?.answers.append(completion) },
            openConnect: { _, args in registry.open(kind: Channel.kindConnect, args: args, hasBytes: true) },
            choiceOf: choiceOf)
    }

    private func hub(isUp: Bool, entries: [String] = ["r1"]) -> HubView {
        var hub = HubView(binding: Samples.binding)
        hub.connection = isUp ? .connected : .connecting
        hub.connectedAddress = isUp ? "https://192.168.1.1:8443" : ""
        hub.services = entries.compactMap { id in
            ChannelServiceEntry.of(.object(["id": .string(id), "type": .string("rdp"), "title": .string("Desk")]))
        }
        return hub
    }

    private func answer(_ result: Result<[String: JSONValue], ClientError> = .success(["password": .string("p")])) {
        let waiting = answers
        answers = []
        for completion in waiting { completion(result) }
    }

    private func turnMainQueue() {
        RunLoop.main.run(until: Date().addingTimeInterval(0.2))
    }

    private func openViewer() throws -> RemoteDesktopTarget {
        let sessions = try XCTUnwrap(self.sessions)
        sessions.take([hub(isUp: true)])
        sessions.connect(bindingId: "b1", entryId: "r1", name: "Home:desk", platformOs: "")
        answer()
        return try XCTUnwrap(sessions.viewing)
    }

    func testConnectIsAJobUntilTheViewerOpensOnAForwardOfItsOwn() throws {
        let sessions = try XCTUnwrap(self.sessions)
        sessions.connect(bindingId: "b1", entryId: "r1", name: "Home:desk", platformOs: "")
        sessions.connect(bindingId: "b1", entryId: "r1", name: "Home:desk", platformOs: "")
        XCTAssertEqual(sessions.connecting, ["b1/r1"])
        XCTAssertEqual(answers.count, 1)
        answer()
        XCTAssertEqual(sessions.connecting, [])
        let target = try XCTUnwrap(sessions.viewing)
        XCTAssertEqual(target.key, "b1/r1")
        XCTAssertEqual(target.host, "127.0.0.1")
        XCTAssertEqual(target.password, "p")
        XCTAssertEqual(target.name, "Home:desk")
        XCTAssertNotNil(LoopbackClient(port: target.port))
    }

    func testEveryAcceptedConnectionIsOneConnectStreamNamingTheEntry() throws {
        let target = try openViewer()
        let client = try XCTUnwrap(LoopbackClient(port: target.port))
        turnMainQueue()
        let open = try XCTUnwrap(socket.frames.first { $0.text("type") == "open" })
        XCTAssertEqual(open.text("kind"), "connect")
        XCTAssertEqual(open.text("id"), "r1")
        _ = client
    }

    func testTheForwardAcceptsNothingWhileItsHubHasNoChannel() throws {
        let target = try openViewer()
        sessions?.take([hub(isUp: false)])
        let client = try XCTUnwrap(LoopbackClient(port: target.port))
        turnMainQueue()
        XCTAssertFalse(socket.frameTypes.contains("open"))
        sessions?.take([hub(isUp: true)])
        turnMainQueue()
        XCTAssertEqual(socket.frameTypes.filter { $0 == "open" }.count, 1)
        _ = client
    }

    func testTheViewerOpensWithTheEntrysKeptChoiceAndPlatform() throws {
        let kept = RemoteDesktopChoice(codec: .av1, quality: .low)
        let sessions = try XCTUnwrap(makeSessions(choiceOf: { $0 == "b1/r1" ? kept : RemoteDesktopChoice() }))
        sessions.connect(bindingId: "b1", entryId: "r1", name: "x", platformOs: "linux")
        answer()
        XCTAssertEqual(sessions.viewing?.choice, kept)
        XCTAssertEqual(sessions.viewing?.platformOs, "linux")
        sessions.close()
    }

    func testAConnectWhileAViewerIsOpenIsDropped() throws {
        _ = try openViewer()
        sessions?.connect(bindingId: "b1", entryId: "r2", name: "y", platformOs: "")
        XCTAssertEqual(sessions?.connecting, [])
        XCTAssertTrue(answers.isEmpty)
        XCTAssertEqual(sessions?.viewing?.key, "b1/r1")
    }

    func testARefusedConnectWritesItsCodeAndMakesNoForward() throws {
        let sessions = try XCTUnwrap(self.sessions)
        sessions.connect(bindingId: "b1", entryId: "r1", name: "x", platformOs: "")
        answer(.failure(.refusal("rdp_not_shared")))
        XCTAssertEqual(sessions.errors["b1/r1"]?.code, "rdp_not_shared")
        XCTAssertNil(sessions.viewing)
        sessions.clearErrors()
        XCTAssertEqual(sessions.errors, [:])
    }

    func testClosingTheViewerEndsItsForward() throws {
        let target = try openViewer()
        sessions?.close()
        turnMainQueue()
        XCTAssertNil(sessions?.viewing)
        XCTAssertNil(LoopbackClient(port: target.port))
    }

    func testTheForwardEndsWhenItsHubWithdrawsTheEntryAndTheViewerStays() throws {
        let target = try openViewer()
        sessions?.take([hub(isUp: true, entries: [])])
        turnMainQueue()
        XCTAssertNil(LoopbackClient(port: target.port))
        XCTAssertEqual(sessions?.viewing?.key, "b1/r1")
    }

    func testLeavingTheHubClosesItsViewerAndDropsItsErrors() throws {
        let sessions = try XCTUnwrap(self.sessions)
        sessions.connect(bindingId: "b2", entryId: "r9", name: "z", platformOs: "")
        answer(.failure(.refusal("rdp_not_shared")))
        let target = try openViewer()
        sessions.forget(bindingId: "b3")
        XCTAssertEqual(sessions.viewing?.key, "b1/r1")
        sessions.forget(bindingId: "b1")
        turnMainQueue()
        XCTAssertNil(sessions.viewing)
        XCTAssertNil(LoopbackClient(port: target.port))
        XCTAssertEqual(sessions.errors.keys.sorted(), ["b2/r9"])
        sessions.forget(bindingId: "b2")
        XCTAssertEqual(sessions.errors, [:])
    }
}
