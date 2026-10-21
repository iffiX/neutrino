import XCTest

@testable import Neutrino

final class RemoteDesktopButtonTests: XCTestCase {
    func testKeyboardFollowsTheKeyboardsOwnStateFloatingOrNot() {
        let floating = RemoteDesktopKeyboard(isShown: true, height: 0)
        XCTAssertTrue(RemoteDesktopButton.keyboard.isActive(keyboard: floating, isKeyBarShown: false))
        var wanted: [Bool] = []
        RemoteDesktopButton.keyboard.press(
            keyboard: floating, isKeyBarShown: false, onKeyboard: { wanted.append($0) }, onKeyBar: { _ in },
            onClose: {})
        RemoteDesktopButton.keyboard.press(
            keyboard: RemoteDesktopKeyboard(), isKeyBarShown: false, onKeyboard: { wanted.append($0) },
            onKeyBar: { _ in }, onClose: {})
        XCTAssertEqual(wanted, [false, true])
    }

    func testKeysTogglesTheKeyBarAndCloseEndsTheSession() {
        var bar: [Bool] = []
        var closes = 0
        for button in [RemoteDesktopButton.keys, .close] {
            button.press(
                keyboard: RemoteDesktopKeyboard(), isKeyBarShown: true, onKeyboard: { _ in },
                onKeyBar: { bar.append($0) }, onClose: { closes += 1 })
        }
        XCTAssertEqual(bar, [false])
        XCTAssertEqual(closes, 1)
        XCTAssertTrue(RemoteDesktopButton.close.isDanger)
        XCTAssertFalse(RemoteDesktopButton.close.isActive(keyboard: RemoteDesktopKeyboard(), isKeyBarShown: true))
    }
}
