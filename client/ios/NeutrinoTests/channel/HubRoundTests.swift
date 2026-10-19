import XCTest

@testable import Neutrino

final class HubRoundTests: XCTestCase {
    private var transport = FakeHubTransport()
    private var clock = FakeClientClock()
    private var won: HubRoundDial?
    private var lost: [(url: String, refusal: ClientError)]?
    private var held: HubRound?

    override func setUp() {
        transport = FakeHubTransport()
        clock = FakeClientClock()
        won = nil
        lost = nil
        held = nil
    }

    private func round() -> HubRound {
        let round = HubRound(
            transport: transport, fingerprint: Samples.fingerprint, clock: clock, onWin: { self.won = $0 },
            onLose: { self.lost = $0 })
        held = round
        return round
    }

    private let refused = ClientError.refusal(Channel.codeHubUnreachable, ["detail": "Connection refused"])

    func testEveryAddressIsDialledAtOnce() {
        let urls = ["https://192.168.1.1:8443", "https://100.88.0.1:8443", "https://203.0.113.7:8443"]
        round().start(urls: urls)
        XCTAssertEqual(transport.sockets.map(\.url), urls)
    }

    func testTheFirstSocketToOpenWinsAndEveryOtherIsClosedBeforeAnyHello() {
        let round = self.round()
        round.start(urls: ["https://a:1", "https://b:1", "https://c:1"])
        transport.sockets[1].deliver(.opened)
        XCTAssertEqual(won?.url, "https://b:1")
        XCTAssertTrue(transport.sockets[0].isClosed)
        XCTAssertTrue(transport.sockets[2].isClosed)
        XCTAssertFalse(transport.sockets[1].isClosed)
        XCTAssertTrue(transport.sockets.allSatisfy { $0.texts.isEmpty })
        transport.sockets[0].deliver(.opened)
        XCTAssertEqual(won?.url, "https://b:1")
    }

    func testARefusedAddressIsDialledAgainEverySecondUntilTheConnectTimeEnds() {
        round().start(urls: ["https://a:1"])
        transport.sockets[0].deliver(.failed(refused, isPortClosed: true))
        for second in 1...9 {
            clock.advance(by: 1)
            XCTAssertEqual(transport.sockets(to: "https://a:1").count, second + 1)
            transport.sockets.last?.deliver(.failed(refused, isPortClosed: true))
        }
        clock.advance(by: 1)
        XCTAssertEqual(lost?.map { $0.refusal }, [refused])
        clock.advance(by: 5)
        XCTAssertEqual(transport.sockets(to: "https://a:1").count, 10)
    }

    func testARedialThatOpensWins() {
        round().start(urls: ["https://a:1", "https://b:1"])
        transport.sockets[0].deliver(.failed(refused, isPortClosed: true))
        clock.advance(by: 1)
        transport.sockets(to: "https://a:1").last?.deliver(.opened)
        XCTAssertEqual(won?.url, "https://a:1")
        XCTAssertTrue(transport.sockets(to: "https://b:1")[0].isClosed)
    }

    func testAnAddressThatDoesNotAnswerIsNotDialledAgain() {
        round().start(urls: ["https://a:1"])
        clock.advance(by: 10)
        XCTAssertEqual(transport.sockets.count, 1)
        XCTAssertEqual(lost?.first?.refusal.code, Channel.codeHubUnreachable)
    }

    func testAnAddressThatFailsOtherwiseIsNotDialledAgainAndTheRoundEndsWhenAllFailed() {
        round().start(urls: ["https://a:1", "https://b:1"])
        let untrusted = ClientError.refusal(Channel.codeHubUntrusted, ["url": "https://a:1"])
        transport.sockets[0].deliver(.failed(untrusted, isPortClosed: false))
        XCTAssertNil(lost)
        transport.sockets[1].deliver(.closed(code: 1006))
        XCTAssertEqual(lost?.map { $0.url }, ["https://a:1", "https://b:1"])
        clock.advance(by: 5)
        XCTAssertEqual(transport.sockets.count, 2)
    }

    func testTheRoundWaitsForTheHubsNameAndDialsItsAddress() {
        let round = self.round()
        round.expectName()
        round.start(urls: ["https://a:1"])
        transport.sockets[0].deliver(.failed(refused, isPortClosed: false))
        XCTAssertNil(lost)
        round.nameResolved("https://10.0.0.1:1")
        XCTAssertEqual(round.nameUrl, "https://10.0.0.1:1")
        transport.sockets(to: "https://10.0.0.1:1").first?.deliver(.opened)
        XCTAssertEqual(won?.url, "https://10.0.0.1:1")
    }

    func testACancelledRoundClosesEverySocketAndCallsNothing() {
        let round = self.round()
        round.start(urls: ["https://a:1", "https://b:1"])
        round.cancel()
        XCTAssertTrue(transport.sockets.allSatisfy(\.isClosed))
        clock.advance(by: 20)
        XCTAssertNil(won)
        XCTAssertNil(lost)
    }
}
