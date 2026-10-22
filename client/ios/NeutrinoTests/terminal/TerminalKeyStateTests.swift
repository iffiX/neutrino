import XCTest

@testable import Neutrino

final class TerminalKeyStateTests: XCTestCase {
    func testAHeldModifierIsSpentOnceOnTheNextKey() {
        let keys = TerminalKeyState()
        keys.toggle(.ctrl)
        keys.toggle(.alt)
        XCTAssertEqual(keys.modifiers, TerminalModifiers(isCtrl: true, isAlt: true))
        XCTAssertEqual(keys.spend(), TerminalModifiers(isCtrl: true, isAlt: true))
        XCTAssertEqual(keys.modifiers, TerminalModifiers())
        XCTAssertEqual(keys.spend(), TerminalModifiers())
    }

    func testTheKeyRowStartsShownAndKeysHidesAndShowsIt() {
        let keys = TerminalKeyState()
        XCTAssertTrue(keys.isRowShown)
        keys.toggleRow()
        XCTAssertFalse(keys.isRowShown)
        keys.toggleRow()
        XCTAssertTrue(keys.isRowShown)
    }

    func testASecondPressLetsTheModifierGo() {
        let keys = TerminalKeyState()
        keys.toggle(.shift)
        keys.toggle(.shift)
        XCTAssertEqual(keys.modifiers, TerminalModifiers())
    }
}
