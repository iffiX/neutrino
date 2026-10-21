import XCTest

@testable import Neutrino

final class RemoteDesktopCodecTests: XCTestCase {
    func testTheCoreOffersAutoAndTheThreeSoftwareCodecs() {
        XCTAssertEqual(RemoteDesktopCodec.allCases.map(\.coreName), ["auto", "vp8", "vp9", "av1"])
        XCTAssertEqual(RemoteDesktopCodec.allCases.map(\.title), ["", "VP8", "VP9", "AV1"])
    }

    func testANameTheAppDoesNotKnowIsAuto() {
        XCTAssertEqual(RemoteDesktopCodec.of("vp9"), .vp9)
        XCTAssertEqual(RemoteDesktopCodec.of("h264"), .auto)
        XCTAssertEqual(RemoteDesktopCodec.of(""), .auto)
    }
}
