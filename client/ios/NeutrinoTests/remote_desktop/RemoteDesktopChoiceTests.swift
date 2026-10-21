import XCTest

@testable import Neutrino

final class RemoteDesktopChoiceTests: XCTestCase {
    func testAChoiceSetsTheTwoSessionOptions() {
        let options = RemoteDesktopChoice(codec: .vp8, quality: .low).options
        XCTAssertEqual(options.map(\.0), ["codec-preference", "image-quality"])
        XCTAssertEqual(options.map(\.1), ["vp8", "low"])
    }

    func testANewChoiceIsAutoAndBalanced() {
        XCTAssertEqual(RemoteDesktopChoice().options.map(\.1), ["auto", "balanced"])
    }
}
