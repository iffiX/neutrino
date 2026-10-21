import XCTest

@testable import Neutrino

final class RemoteDesktopKeyTests: XCTestCase {
    func testTheBarHoldsEscTabTheFourModifiersAndTheArrows() {
        XCTAssertEqual(
            RemoteDesktopKey.allCases.map(\.label), ["Esc", "Tab", "Ctrl", "Shift", "Alt", "Win", "←", "↑", "↓", "→"])
        XCTAssertEqual(RemoteDesktopKey.allCases.filter(\.isModifier), [.ctrl, .shift, .alt, .win])
    }

    func testALetterOrADigitHasAKeyAndAnythingElseHasNone() {
        XCTAssertEqual(RemoteDesktopKey.code(of: "c"), "VK_C")
        XCTAssertEqual(RemoteDesktopKey.code(of: "Z"), "VK_Z")
        XCTAssertEqual(RemoteDesktopKey.code(of: "7"), "VK_7")
        XCTAssertNil(RemoteDesktopKey.code(of: "."))
        XCTAssertNil(RemoteDesktopKey.code(of: "é"))
        XCTAssertNil(RemoteDesktopKey.code(of: "你"))
    }
}
