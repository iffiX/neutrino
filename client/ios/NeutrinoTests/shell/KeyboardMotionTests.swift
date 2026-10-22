import UIKit
import XCTest

@testable import Neutrino

final class KeyboardMotionTests: XCTestCase {
    func testAKeyboardAtTheFootCoversItsHeightAboveTheSafeArea() {
        let keyboard = CGRect(x: 0, y: 852 - 336, width: 393, height: 336)
        XCTAssertEqual(KeyboardMotion.overlap(of: keyboard, windowHeight: 852, safeBottom: 34), 302)
    }

    func testAKeyboardBelowTheWindowCoversNothing() {
        let keyboard = CGRect(x: 0, y: 852, width: 393, height: 336)
        XCTAssertEqual(KeyboardMotion.overlap(of: keyboard, windowHeight: 852, safeBottom: 34), 0)
    }

    func testAKeyboardHalfwayInCoversWhatIsAboveTheSafeArea() {
        let keyboard = CGRect(x: 0, y: 852 - 20, width: 393, height: 336)
        XCTAssertEqual(KeyboardMotion.overlap(of: keyboard, windowHeight: 852, safeBottom: 34), 0)
        let higher = CGRect(x: 0, y: 852 - 100, width: 393, height: 336)
        XCTAssertEqual(KeyboardMotion.overlap(of: higher, windowHeight: 852, safeBottom: 34), 66)
    }

    func testAFloatingKeyboardCoversNothing() {
        let keyboard = CGRect(x: 100, y: 400, width: 320, height: 250)
        XCTAssertEqual(KeyboardMotion.overlap(of: keyboard, windowHeight: 1194, safeBottom: 20), 0)
    }
}
