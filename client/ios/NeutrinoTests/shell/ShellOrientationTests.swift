import UIKit
import XCTest

@testable import Neutrino

final class ShellOrientationTests: XCTestCase {
    func testTheHousingIsAtTheRightOnlyInLandscapeLeft() {
        XCTAssertTrue(ShellOrientation.isHousingRight(.landscapeLeft))
        XCTAssertFalse(ShellOrientation.isHousingRight(.landscapeRight))
        XCTAssertFalse(ShellOrientation.isHousingRight(.portrait))
        XCTAssertFalse(ShellOrientation.isHousingRight(.portraitUpsideDown))
    }
}
