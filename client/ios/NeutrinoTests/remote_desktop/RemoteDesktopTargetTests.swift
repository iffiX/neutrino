import XCTest

@testable import Neutrino

final class RemoteDesktopTargetTests: XCTestCase {
    func testTheHubsAnswerGivesTheForwardOnTheLoopbackWithTheSeatPassword() throws {
        let target = try RemoteDesktopTarget.of(
            key: "b1/r1", name: "Home:desk", answer: .success(["password": .string("seat")]), localPort: 31118
        ).get()
        XCTAssertEqual(target.host, "127.0.0.1")
        XCTAssertEqual(target.port, 31118)
        XCTAssertEqual(target.password, "seat")
        XCTAssertFalse(target.description.contains("seat"))
    }

    func testARefusalStaysTheHubs() {
        let result = RemoteDesktopTarget.of(
            key: "b1/r1", name: "x", answer: .failure(.refusal("rdp_not_shared")), localPort: 31118)
        XCTAssertEqual(result, .failure(.refusal("rdp_not_shared")))
    }
}
