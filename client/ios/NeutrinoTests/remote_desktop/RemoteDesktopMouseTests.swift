import XCTest

@testable import Neutrino

final class RemoteDesktopMouseTests: XCTestCase {
    func testATapMovesThenClicksTheLeftButton() {
        XCTAssertEqual(
            RemoteDesktopMouse.tap(x: 10, y: 20),
            [
                RemoteDesktopMouse(x: 10, y: 20, mask: 0), RemoteDesktopMouse(x: 10, y: 20, mask: 1 | 8),
                RemoteDesktopMouse(x: 10, y: 20, mask: 2 | 8),
            ])
    }

    func testALongPressClicksTheRightButton() {
        XCTAssertEqual(RemoteDesktopMouse.longPress(x: 5, y: 6).map(\.mask), [0, 1 | 16, 2 | 16])
    }

    func testADragHoldsTheLeftButtonFromWhereItLandedToWhereItLeft() {
        XCTAssertEqual(RemoteDesktopMouse.dragStart(x: 1, y: 2).map(\.mask), [0, 1 | 8])
        XCTAssertEqual(RemoteDesktopMouse.dragMove(x: 3, y: 4), RemoteDesktopMouse(x: 3, y: 4, mask: 0))
        XCTAssertEqual(RemoteDesktopMouse.dragEnd(x: 5, y: 6), RemoteDesktopMouse(x: 5, y: 6, mask: 2 | 8))
    }

    func testTheWheelTurnsOneStepPerStepOfTravelAndKeepsTheRest() {
        let step = RemoteDesktop.scrollStepPoints
        let (none, kept) = RemoteDesktopMouse.wheel(travel: step / 2)
        XCTAssertNil(none)
        XCTAssertEqual(kept, step / 2, accuracy: 0.001)
        let (down, rest) = RemoteDesktopMouse.wheel(travel: step * 2.5)
        XCTAssertEqual(down, RemoteDesktopMouse(x: 0, y: 2, mask: 3))
        XCTAssertEqual(rest, step / 2, accuracy: 0.001)
        XCTAssertEqual(RemoteDesktopMouse.wheel(travel: -step).0, RemoteDesktopMouse(x: 0, y: -1, mask: 3))
    }
}
