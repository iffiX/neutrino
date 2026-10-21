import XCTest

@testable import Neutrino

final class RemoteDesktopViewportTests: XCTestCase {
    private let fitted = RemoteDesktopViewport().sized(
        viewWidth: 400, viewHeight: 800, frameWidth: 1920, frameHeight: 1080)

    func testAFrameIsFittedWholeAndCentred() {
        XCTAssertEqual(fitted.drawnWidth, 400, accuracy: 0.001)
        XCTAssertEqual(fitted.drawnHeight, 225, accuracy: 0.001)
        XCTAssertEqual(fitted.left, 0, accuracy: 0.001)
        XCTAssertEqual(fitted.top, 287.5, accuracy: 0.001)
    }

    func testAPinchZoomsAroundItsFocusUpToSixTimes() {
        let zoomed = fitted.zoomed(by: 2, focusX: 200, focusY: 400)
        XCTAssertEqual(zoomed.zoom, 2, accuracy: 0.001)
        XCTAssertEqual(zoomed.drawnWidth, 800, accuracy: 0.001)
        XCTAssertEqual(zoomed.left, -200, accuracy: 0.001)
        XCTAssertEqual(zoomed.toFrame(x: 200, y: 400).x, 960)
        XCTAssertEqual(fitted.zoomed(by: 100, focusX: 0, focusY: 0).zoom, RemoteDesktop.zoomMax, accuracy: 0.001)
        XCTAssertEqual(fitted.zoomed(by: 0.1, focusX: 0, focusY: 0).zoom, 1, accuracy: 0.001)
    }

    func testAPanStopsWhereAnEdgeWouldLeaveAGap() {
        let zoomed = fitted.zoomed(by: 2, focusX: 0, focusY: 0)
        XCTAssertEqual(zoomed.panned(dx: 500, dy: 0).left, 0, accuracy: 0.001)
        XCTAssertEqual(zoomed.panned(dx: -5000, dy: 0).left, -400, accuracy: 0.001)
    }

    func testThePictureMovesUpOverTheKeyboardWithoutShrinking() {
        let covered = fitted.covering(500)
        XCTAssertEqual(covered.drawnHeight, fitted.drawnHeight, accuracy: 0.001)
        XCTAssertEqual(covered.top, fitted.top, accuracy: 0.001)
        XCTAssertEqual(covered.panned(dx: 0, dy: -1000).top, 75, accuracy: 0.001)
    }

    func testAPointMapsToThePixelUnderItKeptInsideThePicture() {
        XCTAssertEqual(fitted.toFrame(x: 200, y: 400).x, 960)
        XCTAssertEqual(fitted.toFrame(x: 200, y: 400).y, 540)
        XCTAssertEqual(fitted.toFrame(x: -10, y: 0).x, 0)
        XCTAssertEqual(fitted.toFrame(x: 1000, y: 1000).y, 1079)
        XCTAssertEqual(RemoteDesktopViewport().toFrame(x: 10, y: 10).x, 0)
    }

    func testARotationFitsThePictureAgain() {
        let zoomed = fitted.zoomed(by: 3, focusX: 100, focusY: 100)
        let turned = zoomed.sized(viewWidth: 800, viewHeight: 400, frameWidth: 1920, frameHeight: 1080)
        XCTAssertEqual(turned.zoom, 1, accuracy: 0.001)
        XCTAssertEqual(turned.drawnHeight, 400, accuracy: 0.001)
        XCTAssertEqual(turned.sized(viewWidth: 800, viewHeight: 400, frameWidth: 1920, frameHeight: 1080), turned)
    }
}
