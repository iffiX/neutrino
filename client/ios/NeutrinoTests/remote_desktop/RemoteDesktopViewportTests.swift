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

    func testAFittedPictureMovesAboveTheKeyBarWithoutShrinkingAndBack() {
        let covered = fitted.covering(350)
        XCTAssertEqual(covered.drawnHeight, fitted.drawnHeight, accuracy: 0.001)
        XCTAssertEqual(covered.top, 112.5, accuracy: 0.001)
        XCTAssertLessThanOrEqual(covered.top + covered.drawnHeight, 450)
        XCTAssertEqual(covered.panned(dx: 0, dy: -1000).top, 112.5, accuracy: 0.001)
        XCTAssertEqual(covered.covering(0), fitted)
    }

    func testAZoomedPictureMovesUpKeepsItsZoomAndPansEverywhere() {
        let zoomed = fitted.zoomed(by: 4, focusX: 200, focusY: 400)
        XCTAssertEqual(zoomed.top, -50, accuracy: 0.001)
        let covered = zoomed.covering(350)
        XCTAssertEqual(covered.zoom, 4, accuracy: 0.001)
        XCTAssertEqual(covered.left, zoomed.left, accuracy: 0.001)
        XCTAssertEqual(covered.top, -400, accuracy: 0.001)
        XCTAssertEqual(covered.toFrame(x: 200, y: 449).y, zoomed.toFrame(x: 200, y: 799).y)
        let bottom = covered.panned(dx: 0, dy: -1000)
        XCTAssertEqual(bottom.top + bottom.drawnHeight, 450, accuracy: 0.001)
        XCTAssertEqual(covered.panned(dx: 0, dy: 1000).top, 0, accuracy: 0.001)
        XCTAssertEqual(covered.covering(0), zoomed)
    }

    func testATallPictureShowsItsBottomEdgeAboveTheKeyBar() {
        let landscape = RemoteDesktopViewport().sized(
            viewWidth: 844, viewHeight: 390, frameWidth: 1920, frameHeight: 1080)
        let covered = landscape.covering(250)
        XCTAssertEqual(covered.top + covered.drawnHeight, 140, accuracy: 0.001)
        XCTAssertEqual(covered.panned(dx: 0, dy: 1000).top, 0, accuracy: 0.001)
        XCTAssertEqual(covered.covering(0).top, landscape.top, accuracy: 0.001)
    }

    func testARotationWithTheKeyBarUpFitsThePictureAndKeepsItAboveTheKeyBar() {
        let turned = fitted.covering(350).sized(viewWidth: 800, viewHeight: 400, frameWidth: 1920, frameHeight: 1080)
        XCTAssertEqual(turned.covered, 350, accuracy: 0.001)
        XCTAssertEqual(turned.zoom, 1, accuracy: 0.001)
        XCTAssertEqual(turned.top + turned.drawnHeight, 50, accuracy: 0.001)
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
