import XCTest

@testable import Neutrino

final class RemoteDesktopQualityTests: XCTestCase {
    func testEachQualityIsWordedByItsKey() {
        XCTAssertEqual(
            RemoteDesktopQuality.allCases.map(\.wordKey),
            ["ui.rdp_quality_balanced", "ui.rdp_quality_low", "ui.rdp_quality_best"])
    }

    func testANameTheAppDoesNotKnowIsBalanced() {
        XCTAssertEqual(RemoteDesktopQuality.of("best"), .best)
        XCTAssertEqual(RemoteDesktopQuality.of("highest"), .balanced)
    }
}
