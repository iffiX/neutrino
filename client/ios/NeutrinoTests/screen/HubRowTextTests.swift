import XCTest

@testable import Neutrino

final class HubRowTextTests: XCTestCase {
    private let words = WordCatalog.load(language: "en", bundle: Bundle(for: ClientCore.self))

    private func hub(_ change: (inout HubView) -> Void) -> HubView {
        var hub = HubView(binding: Samples.binding)
        change(&hub)
        return hub
    }

    func testAWaitCountsDownToItsNextRoundAndReadsConnectingAtZero() {
        let waiting = hub {
            $0.connection = .waiting
            $0.waitReason = .hubSilent
            $0.nextRoundAt = 1005
        }
        XCTAssertEqual(
            HubRowText.stateLine(waiting, words: words, now: 1000), "The hub did not answer · retrying in 5 s")
        XCTAssertEqual(
            HubRowText.stateLine(waiting, words: words, now: 1004.2), "The hub did not answer · retrying in 1 s")
        XCTAssertEqual(HubRowText.stateLine(waiting, words: words, now: 1006), "Connecting…")
    }

    func testARefusedJoinNamesItsCodeAndAnOldClientSaysToUpdate() {
        let refused = hub {
            $0.connection = .waiting
            $0.waitReason = .joinRefused
            $0.waitRefusal = .refusal("ticket_spent")
        }
        XCTAssertTrue(HubRowText.stateLine(refused, words: words, now: 0).hasPrefix("Join refused · "))
        XCTAssertEqual(HubRowText.tone(refused), .bad)
        let old = hub {
            $0.connection = .waiting
            $0.waitReason = .tooOld
            $0.waitRefusal = .refusal(Channel.codeProtocolTooOld)
        }
        XCTAssertEqual(HubRowText.stateLine(old, words: words, now: 0), "Version too old · update the client")
    }

    func testAConnectedRowShowsTheWayInAndTheRoundTripAsTags() {
        let connected = hub {
            $0.connection = .connected
            $0.reachedThrough = "lan"
            $0.rttMs = 3
        }
        XCTAssertEqual(HubRowText.tags(connected, words: words), ["Connected · LAN", "3 ms"])
        XCTAssertEqual(HubRowText.tone(connected), .ok)
    }

    func testAReplacedRowWaitsForReconnect() {
        let replaced = hub {
            $0.connection = .waiting
            $0.waitReason = .replaced
        }
        XCTAssertEqual(HubRowText.stateLine(replaced, words: words, now: 0), "Replaced by another client · Reconnect")
    }
}
