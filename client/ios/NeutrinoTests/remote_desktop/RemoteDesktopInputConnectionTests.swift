import XCTest

@testable import Neutrino

final class RemoteDesktopInputConnectionTests: XCTestCase {
    private var core = FakeRemoteDesktopCore()
    private var clock = FakeClientClock()
    private var connection = RemoteDesktopInputConnection(
        sender: RemoteDesktopInputSender(core: FakeRemoteDesktopCore(), platformOs: "", clock: FakeClientClock()))

    override func setUp() {
        core = FakeRemoteDesktopCore()
        clock = FakeClientClock()
        connection = RemoteDesktopInputConnection(
            sender: RemoteDesktopInputSender(core: core, platformOs: "", clock: clock))
    }

    private func sent() -> [String] {
        clock.advance(by: RemoteDesktop.typePaceSeconds * 10)
        return core.calls
    }

    func testCommittedTextIsSentOneCharacterAtATime() {
        connection.insert("你好")
        XCTAssertEqual(sent(), ["text 你", "text 好"])
    }

    func testMarkedTextIsSentNowhereUntilTheKeyboardCommitsIt() {
        connection.setMarked("n", selection: NSRange(location: 1, length: 0))
        connection.setMarked("ni", selection: NSRange(location: 2, length: 0))
        connection.setMarked("ni hao", selection: NSRange(location: 6, length: 0))
        XCTAssertEqual(sent(), [])
        XCTAssertEqual(connection.marked, "ni hao")
        connection.insert("你好")
        XCTAssertEqual(sent(), ["text 你", "text 好"])
        XCTAssertEqual(connection.marked, "")
    }

    func testMarkedTextTheKeyboardFinishesIsSentOnce() {
        connection.setMarked("你好", selection: NSRange(location: 2, length: 0))
        connection.unmark()
        connection.unmark()
        XCTAssertEqual(sent(), ["text 你", "text 好"])
    }

    func testADeleteShortensTheMarkedTextAndSendsNothing() {
        connection.setMarked("nih", selection: NSRange(location: 3, length: 0))
        connection.deleteBackward()
        XCTAssertEqual(connection.marked, "ni")
        XCTAssertEqual(connection.selection, NSRange(location: 2, length: 0))
        XCTAssertEqual(sent(), [])
    }

    func testADeleteWithNothingMarkedIsBackspace() {
        connection.deleteBackward()
        XCTAssertEqual(sent(), ["key VK_BACK down", "key VK_BACK up"])
    }

    func testASelectionOutsideTheMarkedTextIsKeptInsideIt() {
        connection.setMarked("ab", selection: NSRange(location: 5, length: 3))
        XCTAssertEqual(connection.selection, NSRange(location: 2, length: 0))
    }

    func testAHardwareKeyIsPressed() {
        connection.press(RemoteDesktopKey.left.code)
        XCTAssertEqual(sent(), ["key VK_LEFT down", "key VK_LEFT up"])
    }
}
