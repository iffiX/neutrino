import XCTest

final class JoinPageUITests: XCTestCase {
    private let app = XCUIApplication()

    override func setUp() {
        continueAfterFailure = false
        app.launchArguments = ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
    }

    func testAnEmptyTapClosesTheKeyboard() throws {
        element(containing: "Join a hub").tap()
        let field = pasteField()
        XCTAssertTrue(field.waitForExistence(timeout: 10))
        field.tap()
        let keyboard = app.keyboards.firstMatch
        XCTAssertTrue(keyboard.waitForExistence(timeout: 10), "no software keyboard came up")
        XCTAssertFalse(element(containing: "Settings").exists, "the bottom bar shows above the keyboard")
        field.typeText("not a link")
        try screen("join_1_keyboard_up")

        element(containing: "Join", type: .button).tap()
        XCTAssertTrue(keyboard.exists, "a tap on a control closed the keyboard")

        app.coordinate(withNormalizedOffset: .zero).withOffset(CGVector(dx: 6, dy: 220)).tap()
        XCTAssertTrue(isGone(keyboard), "a tap on empty space left the keyboard up")
        XCTAssertTrue(element(containing: "Settings").waitForExistence(timeout: 5), "the bottom bar did not come back")
        try screen("join_2_after_a_tap_on_empty_space")
    }

    private func element(containing text: String, type: XCUIElement.ElementType = .any) -> XCUIElement {
        app.descendants(matching: type).matching(NSPredicate(format: "label CONTAINS %@", text)).firstMatch
    }

    private func pasteField() -> XCUIElement {
        let lines = app.textViews.firstMatch
        return lines.waitForExistence(timeout: 5) ? lines : app.textFields.firstMatch
    }

    private func isGone(_ element: XCUIElement) -> Bool {
        let gone = expectation(for: NSPredicate(format: "exists == false"), evaluatedWith: element)
        return XCTWaiter.wait(for: [gone], timeout: 10) == .completed
    }

    private func screen(_ name: String) throws {
        let path = ProcessInfo.processInfo.environment["NEUTRINO_SCREENS"] ?? ""
        guard !path.isEmpty else { return }
        let directory = URL(fileURLWithPath: path, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try XCUIScreen.main.screenshot().pngRepresentation.write(to: directory.appendingPathComponent("\(name).png"))
    }
}
