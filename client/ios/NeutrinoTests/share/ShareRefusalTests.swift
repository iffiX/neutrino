import XCTest

@testable import Neutrino

final class ShareRefusalTests: XCTestCase {
    private func code(_ error: Error, hubRefusal: ClientError? = nil, isCarried: Bool = true) -> String {
        ShareRefusal.of(error, hubRefusal: hubRefusal, isCarried: isCarried).code
    }

    func testTheSharesAnswersAreWordedByTheShareCodes() {
        XCTAssertEqual(code(POSIXError(.ECONNREFUSED)), "share_login_rejected")
        XCTAssertEqual(code(POSIXError(.EACCES)), "share_access_denied")
        XCTAssertEqual(code(POSIXError(.ENOENT)), "share_not_found")
        XCTAssertEqual(code(POSIXError(.EEXIST)), "share_name_taken")
        XCTAssertEqual(code(POSIXError(.ETIMEDOUT)), "share_unreachable")
        XCTAssertEqual(code(URLError(.badURL)), "share_unreachable")
    }

    func testEpermIsTheSharesRefusalWhileTheConnectionIsCarriedAndItsEndAfter() {
        XCTAssertEqual(code(POSIXError(.EPERM), isCarried: true), "share_access_denied")
        XCTAssertEqual(code(POSIXError(.EPERM), isCarried: false), "share_unreachable")
    }

    func testTheHubsCodeWinsWhenTheHubRefusedTheForwardsStream() {
        let refusal = ClientError.refusal("agent_offline")
        XCTAssertEqual(code(POSIXError(.EPERM), hubRefusal: refusal, isCarried: false), "agent_offline")
        XCTAssertEqual(code(ClientError.refusal("client_internal"), hubRefusal: refusal), "client_internal")
    }
}
