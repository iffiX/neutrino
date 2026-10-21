import XCTest

@testable import Neutrino

final class RemoteDesktopKeyboardTests: XCTestCase {
    func testADockedKeyboardCoversFromItsTopEdgeDown() {
        let keyboard = RemoteDesktopKeyboard.of(
            frame: CGRect(x: 0, y: 500, width: 400, height: 300), viewHeight: 800)
        XCTAssertEqual(keyboard, RemoteDesktopKeyboard(isShown: true, height: 300))
    }

    func testAFloatingKeyboardIsShownAndCoversNothing() {
        let keyboard = RemoteDesktopKeyboard.of(
            frame: CGRect(x: 50, y: 200, width: 300, height: 250), viewHeight: 800)
        XCTAssertEqual(keyboard, RemoteDesktopKeyboard(isShown: true, height: 0))
    }

    func testAKeyboardMovedOffTheScreenIsHidden() {
        let keyboard = RemoteDesktopKeyboard.of(
            frame: CGRect(x: 0, y: 800, width: 400, height: 300), viewHeight: 800)
        XCTAssertEqual(keyboard, RemoteDesktopKeyboard())
    }
}
