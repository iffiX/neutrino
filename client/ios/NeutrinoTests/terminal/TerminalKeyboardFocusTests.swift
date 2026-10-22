import XCTest

@testable import Neutrino

final class TerminalKeyboardFocusTests: XCTestCase {
    func testRefocusWhenFocusedWithNoKeyboard() {
        XCTAssertTrue(TerminalKeyboardFocus.needsRefocus(isFocused: true, isKeyboardShown: false))
        XCTAssertFalse(TerminalKeyboardFocus.needsRefocus(isFocused: true, isKeyboardShown: true))
        XCTAssertFalse(TerminalKeyboardFocus.needsRefocus(isFocused: false, isKeyboardShown: false))
        XCTAssertFalse(TerminalKeyboardFocus.needsRefocus(isFocused: false, isKeyboardShown: true))
    }
}
