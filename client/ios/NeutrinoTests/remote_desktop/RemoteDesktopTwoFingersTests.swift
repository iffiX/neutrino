import XCTest

@testable import Neutrino

final class RemoteDesktopTwoFingersTests: XCTestCase {
    private let slop = RemoteDesktop.pinchSlopPoints

    func testNothingHappensUntilTheFingersMovePastTheSlop() {
        var fingers = RemoteDesktopTwoFingers()
        XCTAssertNil(fingers.move(centreX: 100, centreY: 100, spread: 100))
        XCTAssertNil(fingers.move(centreX: 100, centreY: 100 + slop / 2, spread: 100 + slop / 2))
        XCTAssertEqual(fingers.mode, .undecided)
    }

    func testASpreadChangingFirstIsAPinchThatZoomsAndMoves() {
        var fingers = RemoteDesktopTwoFingers()
        _ = fingers.move(centreX: 100, centreY: 100, spread: 100)
        let step = fingers.move(centreX: 110, centreY: 100, spread: 200)
        XCTAssertEqual(fingers.mode, .pinch)
        XCTAssertEqual(step, .pinch(factor: 2, focusX: 110, focusY: 100, dx: 10, dy: 0))
        XCTAssertEqual(
            fingers.move(centreX: 110, centreY: 300, spread: 200),
            .pinch(factor: 1, focusX: 110, focusY: 300, dx: 0, dy: 200)
        )
    }

    func testTheCentreMovingFirstIsAScrollThatTurnsTheWheel() {
        var fingers = RemoteDesktopTwoFingers()
        _ = fingers.move(centreX: 100, centreY: 100, spread: 100)
        let step = fingers.move(centreX: 100, centreY: 100 + slop * 3, spread: 100)
        XCTAssertEqual(fingers.mode, .scroll)
        XCTAssertEqual(step, .wheel(RemoteDesktopMouse(x: 0, y: 3, mask: RemoteDesktop.mouseWheel)))
        XCTAssertNil(fingers.move(centreX: 100, centreY: 100 + slop * 3.5, spread: 140))
        XCTAssertEqual(fingers.mode, .scroll)
        XCTAssertEqual(
            fingers.move(centreX: 100, centreY: 100 + slop * 4, spread: 100),
            .wheel(RemoteDesktopMouse(x: 0, y: 1, mask: RemoteDesktop.mouseWheel)))
    }
}
