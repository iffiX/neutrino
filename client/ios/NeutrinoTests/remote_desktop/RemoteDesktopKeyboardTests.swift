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

    func testTheKeyBarAboveTheKeyboardCoversFromItsTopEdgeDown() {
        let keyboard = RemoteDesktopKeyboard(isShown: true, height: 300)
        XCTAssertEqual(keyboard.covered(keyBarTop: 450, viewHeight: 800), 350, accuracy: 0.001)
    }

    func testTheKeyBarAloneCoversFromItsTopEdgeDown() {
        XCTAssertEqual(RemoteDesktopKeyboard().covered(keyBarTop: 716, viewHeight: 800), 84, accuracy: 0.001)
    }

    func testWithTheKeyBarHiddenOnlyTheKeyboardCovers() {
        let keyboard = RemoteDesktopKeyboard(isShown: true, height: 300)
        XCTAssertEqual(keyboard.covered(keyBarTop: nil, viewHeight: 800), 300, accuracy: 0.001)
        XCTAssertEqual(RemoteDesktopKeyboard().covered(keyBarTop: nil, viewHeight: 800), 0, accuracy: 0.001)
    }
}
