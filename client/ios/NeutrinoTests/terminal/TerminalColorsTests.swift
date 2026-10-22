import UIKit
import XCTest

@testable import Neutrino

final class TerminalColorsTests: XCTestCase {
    private func assertColour(
        _ colour: UIColor, _ hex: UInt32, alpha: CGFloat = 1, file: StaticString = #filePath, line: UInt = #line
    ) {
        var red: CGFloat = 0
        var green: CGFloat = 0
        var blue: CGFloat = 0
        var opacity: CGFloat = 0
        XCTAssertTrue(colour.getRed(&red, green: &green, blue: &blue, alpha: &opacity), file: file, line: line)
        XCTAssertEqual(red, CGFloat((hex >> 16) & 0xFF) / 255, accuracy: 0.002, file: file, line: line)
        XCTAssertEqual(green, CGFloat((hex >> 8) & 0xFF) / 255, accuracy: 0.002, file: file, line: line)
        XCTAssertEqual(blue, CGFloat(hex & 0xFF) / 255, accuracy: 0.002, file: file, line: line)
        XCTAssertEqual(opacity, alpha, accuracy: 0.002, file: file, line: line)
    }

    func testTheSixteenColoursAreTheTangoPaletteInBothThemes() {
        let tango: [UInt32] = [
            0x2E3436, 0xCC0000, 0x4E9A06, 0xC4A000, 0x3465A4, 0x75507B, 0x06989A, 0xD3D7CF,
            0x555753, 0xEF2929, 0x8AE234, 0xFCE94F, 0x729FCF, 0xAD7FA8, 0x34E2E2, 0xEEEEEC,
        ]
        XCTAssertEqual(TerminalColors(palette: .dark).ansi, tango)
        XCTAssertEqual(TerminalColors(palette: .light).ansi, tango)
    }

    func testTheDarkThemeDrawsLightTextOnThePagesDarkBackground() {
        let colours = TerminalColors(palette: .dark)
        assertColour(colours.background, 0x070809)
        assertColour(colours.foreground, 0xE6EDF3)
        assertColour(colours.cursor, 0x22D3EE)
        assertColour(colours.selection, 0x22D3EE, alpha: 0.25)
        XCTAssertEqual(colours.indicator, .white)
    }

    func testTheLightThemeDrawsDarkTextOnThePagesLightBackground() {
        let colours = TerminalColors(palette: .light)
        assertColour(colours.background, 0xE8EBF0)
        assertColour(colours.foreground, 0x0F172A)
        assertColour(colours.cursor, 0x0C6A84)
        assertColour(colours.selection, 0x0C6A84, alpha: 0.25)
        XCTAssertEqual(colours.indicator, .black)
    }
}
