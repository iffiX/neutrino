import XCTest

@testable import Neutrino

final class RustDeskRemoteDesktopCoreTests: XCTestCase {
    func testTheCoresReportsMoveTheConnection() {
        let connecting = RemoteDesktopState.connecting
        XCTAssertEqual(
            RustDeskRemoteDesktopCore.next(connecting, report: RemoteDesktop.stateConnected, text: ""), .showing)
        XCTAssertEqual(
            RustDeskRemoteDesktopCore.next(connecting, report: RemoteDesktop.stateLoginFailed, text: ""),
            .stopped(.refusal("rdp_login_failed")))
        XCTAssertEqual(
            RustDeskRemoteDesktopCore.next(.showing, report: RemoteDesktop.stateClosed, text: "Connection reset"),
            .stopped(.refusal("rdp_closed", ["reason": "Connection reset"])))
        XCTAssertEqual(RustDeskRemoteDesktopCore.next(connecting, report: 99, text: ""), connecting)
    }

    func testAStoppedConnectionStaysStopped() {
        let stopped = RemoteDesktopState.stopped(.refusal("rdp_login_failed"))
        XCTAssertEqual(RustDeskRemoteDesktopCore.next(stopped, report: RemoteDesktop.stateConnected, text: ""), stopped)
    }

    func testABuildWithoutTheCoreStopsAtOnceAndSendsNothing() throws {
        try XCTSkipIf(RustDeskNative.isLinked, "this build links the core")
        let core = RustDeskRemoteDesktopCore(appDir: NSTemporaryDirectory())
        var states: [RemoteDesktopState] = []
        core.connect(
            target: RemoteDesktopTarget(key: "b1/r1", name: "x", host: "127.0.0.1", port: 1, password: "p"),
            onState: { states.append($0) }, onFrameSize: { _, _ in }, onClipboard: { _ in })
        XCTAssertEqual(states, [.stopped(.refusal("rdp_launch_failed", ["detail": "-1"]))])
        core.mouse(RemoteDesktopMouse(x: 1, y: 1, mask: RemoteDesktop.mouseMove))
        core.disconnect()
    }
}
