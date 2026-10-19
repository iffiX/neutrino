import XCTest

@testable import Neutrino

final class TerminalKeyTests: XCTestCase {
    private func text(_ data: Data) -> String {
        String(decoding: data, as: UTF8.self)
    }

    func testTheRowHoldsItsKeysInOrder() {
        XCTAssertEqual(TerminalKey.allCases.map(\.label), ["Esc", "Tab", "Ctrl", "Shift", "Alt", "←", "↑", "↓", "→"])
    }

    func testEachKeySendsWhatXtermDoes() {
        let none = TerminalModifiers()
        XCTAssertEqual(text(TerminalKey.escape.sequence(none)), "\u{1b}")
        XCTAssertEqual(text(TerminalKey.tab.sequence(none)), "\t")
        XCTAssertEqual(text(TerminalKey.tab.sequence(TerminalModifiers(isShift: true))), "\u{1b}[Z")
        XCTAssertEqual(text(TerminalKey.up.sequence(none)), "\u{1b}[A")
        XCTAssertEqual(text(TerminalKey.up.sequence(none, isApplicationCursor: true)), "\u{1b}OA")
        XCTAssertEqual(text(TerminalKey.left.sequence(TerminalModifiers(isCtrl: true))), "\u{1b}[1;5D")
        XCTAssertEqual(text(TerminalKey.right.sequence(TerminalModifiers(isShift: true, isAlt: true))), "\u{1b}[1;4C")
        XCTAssertEqual(text(TerminalKey.escape.sequence(TerminalModifiers(isAlt: true))), "\u{1b}\u{1b}")
        XCTAssertTrue(TerminalKey.ctrl.sequence(none).isEmpty)
    }

    func testAHeldModifierIsSpentOnTheNextTypedKey() {
        XCTAssertEqual(TerminalModifiers(isCtrl: true).applied(to: Data("c".utf8)), Data([0x03]))
        XCTAssertEqual(TerminalModifiers(isCtrl: true).applied(to: Data("[".utf8)), Data([0x1b]))
        XCTAssertEqual(TerminalModifiers(isShift: true).applied(to: Data("q".utf8)), Data("Q".utf8))
        XCTAssertEqual(TerminalModifiers(isAlt: true).applied(to: Data("b".utf8)), Data([0x1b, 0x62]))
        XCTAssertEqual(TerminalModifiers(isCtrl: true).applied(to: Data("ab".utf8)), Data("ab".utf8))
    }

    func testAPressOnAModifierHoldsItOrLetsItGo() {
        let held = TerminalModifiers().toggled(.ctrl)
        XCTAssertTrue(held.isHeld(.ctrl))
        XCTAssertFalse(held.toggled(.ctrl).isHeld(.ctrl))
        XCTAssertEqual(TerminalModifiers().toggled(.up), TerminalModifiers())
    }
}
