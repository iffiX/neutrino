import XCTest

@testable import Neutrino

final class FlowRowTests: XCTestCase {
    func testViewsThatFitShareOneLine() {
        XCTAssertEqual(FlowRow.lines(widths: [50, 60, 70], width: 200, spacing: 8), [[0, 1, 2]])
    }

    func testAViewThatDoesNotFitStartsTheNextLine() {
        XCTAssertEqual(FlowRow.lines(widths: [100, 60, 50], width: 160, spacing: 8), [[0], [1, 2]])
        XCTAssertEqual(FlowRow.lines(widths: [80, 80, 80], width: 168, spacing: 8), [[0, 1], [2]])
    }

    func testAViewWiderThanTheLineTakesALineOfItsOwn() {
        XCTAssertEqual(FlowRow.lines(widths: [40, 300, 40], width: 200, spacing: 8), [[0], [1], [2]])
    }

    func testNoViewsMakeNoLines() {
        XCTAssertEqual(FlowRow.lines(widths: [], width: 200, spacing: 8), [])
    }
}
