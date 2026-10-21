import XCTest

@testable import Neutrino

final class MissingRemoteDesktopCoreTests: XCTestCase {
    func testEveryConnectionStopsAtOnceWithRdpCoreMissing() {
        var states: [RemoteDesktopState] = []
        MissingRemoteDesktopCore().connect(
            target: RemoteDesktopTarget(key: "b1/r1", name: "x", host: "127.0.0.1", port: 1, password: "p"),
            onState: { states.append($0) }, onFrameSize: { _, _ in }, onClipboard: { _ in })
        XCTAssertEqual(states, [.stopped(.refusal("rdp_core_missing"))])
    }
}
