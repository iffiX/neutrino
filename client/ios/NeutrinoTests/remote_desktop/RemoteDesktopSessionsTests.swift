import XCTest

@testable import Neutrino

final class RemoteDesktopSessionsTests: XCTestCase {
    private var held: [String] = []
    private var released: [String] = []
    private var bound = Result<Int, ClientError>.success(31118)
    private var answers: [(Result<[String: JSONValue], ClientError>) -> Void] = []

    override func setUp() {
        held = []
        released = []
        bound = .success(31118)
        answers = []
    }

    private func sessions(choiceOf: @escaping (String) -> RemoteDesktopChoice = { _ in RemoteDesktopChoice() })
        -> RemoteDesktopSessions
    {
        RemoteDesktopSessions(
            material: { [weak self] _, _, completion in self?.answers.append(completion) },
            forward: { [weak self] bindingId, entryId, port in
                self?.held.append("\(bindingId)/\(entryId):\(port)")
                return self?.bound ?? .success(0)
            },
            release: { [weak self] bindingId, entryId in self?.released.append("\(bindingId)/\(entryId)") },
            choiceOf: choiceOf)
    }

    private func answer(_ result: Result<[String: JSONValue], ClientError> = .success(["password": .string("p")])) {
        let waiting = answers
        answers = []
        for completion in waiting { completion(result) }
    }

    func testConnectIsAJobUntilTheViewerOpensOnTheForward() {
        let sessions = self.sessions()
        sessions.connect(bindingId: "b1", entryId: "r1", name: "Home:desk", platformOs: "", port: 21118)
        sessions.connect(bindingId: "b1", entryId: "r1", name: "Home:desk", platformOs: "", port: 21118)
        XCTAssertEqual(sessions.connecting, ["b1/r1"])
        XCTAssertEqual(answers.count, 1)
        answer()
        XCTAssertEqual(sessions.connecting, [])
        XCTAssertEqual(held, ["b1/r1:21118"])
        let target = sessions.viewing
        XCTAssertEqual(target?.key, "b1/r1")
        XCTAssertEqual(target?.host, "127.0.0.1")
        XCTAssertEqual(target?.port, 31118)
        XCTAssertEqual(target?.password, "p")
        XCTAssertEqual(target?.name, "Home:desk")
    }

    func testTheViewerOpensWithTheEntrysKeptChoiceAndPlatform() {
        let kept = RemoteDesktopChoice(codec: .av1, quality: .low)
        let sessions = self.sessions(choiceOf: { $0 == "b1/r1" ? kept : RemoteDesktopChoice() })
        sessions.connect(bindingId: "b1", entryId: "r1", name: "x", platformOs: "linux", port: 21118)
        answer()
        XCTAssertEqual(sessions.viewing?.choice, kept)
        XCTAssertEqual(sessions.viewing?.platformOs, "linux")
    }

    func testAConnectWhileAViewerIsOpenIsDropped() {
        let sessions = self.sessions()
        sessions.connect(bindingId: "b1", entryId: "r1", name: "x", platformOs: "", port: 21118)
        answer()
        sessions.connect(bindingId: "b1", entryId: "r2", name: "y", platformOs: "", port: 21118)
        XCTAssertEqual(sessions.connecting, [])
        XCTAssertTrue(answers.isEmpty)
        XCTAssertEqual(sessions.viewing?.key, "b1/r1")
    }

    func testARefusedConnectWritesItsCodeAndMakesNoForward() {
        let sessions = self.sessions()
        sessions.connect(bindingId: "b1", entryId: "r1", name: "x", platformOs: "", port: 21118)
        answer(.failure(.refusal("rdp_not_shared")))
        XCTAssertEqual(sessions.errors["b1/r1"]?.code, "rdp_not_shared")
        XCTAssertNil(sessions.viewing)
        XCTAssertEqual(held, [])
        sessions.clearErrors()
        XCTAssertEqual(sessions.errors, [:])
    }

    func testAForwardThatFailsWritesItsCode() {
        bound = .failure(.refusal("forward_failed", ["detail": "no local port is free"]))
        let sessions = self.sessions()
        sessions.connect(bindingId: "b1", entryId: "r1", name: "x", platformOs: "", port: 21118)
        answer()
        XCTAssertEqual(sessions.errors["b1/r1"]?.code, "forward_failed")
        XCTAssertNil(sessions.viewing)
    }

    func testClosingTheViewerEndsTheForwardOnce() {
        let sessions = self.sessions()
        sessions.connect(bindingId: "b1", entryId: "r1", name: "x", platformOs: "", port: 21118)
        answer()
        sessions.close()
        XCTAssertNil(sessions.viewing)
        XCTAssertEqual(released, ["b1/r1"])
        sessions.close()
        XCTAssertEqual(released, ["b1/r1"])
    }

    func testLeavingTheHubClosesItsViewerAndDropsItsErrors() {
        let sessions = self.sessions()
        sessions.connect(bindingId: "b2", entryId: "r9", name: "z", platformOs: "", port: 21118)
        answer(.failure(.refusal("rdp_not_shared")))
        sessions.connect(bindingId: "b1", entryId: "r1", name: "x", platformOs: "", port: 21118)
        answer()
        sessions.forget(bindingId: "b3")
        XCTAssertEqual(sessions.viewing?.key, "b1/r1")
        sessions.forget(bindingId: "b1")
        XCTAssertNil(sessions.viewing)
        XCTAssertEqual(released, ["b1/r1"])
        XCTAssertEqual(sessions.errors.keys.sorted(), ["b2/r9"])
        sessions.forget(bindingId: "b2")
        XCTAssertEqual(sessions.errors, [:])
    }
}
