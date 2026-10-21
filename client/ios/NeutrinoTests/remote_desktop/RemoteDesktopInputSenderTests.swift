import XCTest

@testable import Neutrino

final class RemoteDesktopInputSenderTests: XCTestCase {
    private var core = FakeRemoteDesktopCore()
    private var clock = FakeClientClock()
    private var reported: [Set<RemoteDesktopKey>] = []

    override func setUp() {
        core = FakeRemoteDesktopCore()
        clock = FakeClientClock()
        reported = []
    }

    private func sender(platformOs: String = "") -> RemoteDesktopInputSender {
        let sender = RemoteDesktopInputSender(core: core, platformOs: platformOs, clock: clock)
        sender.onHeld = { [weak self] keys in self?.reported.append(keys) }
        return sender
    }

    private func drain() {
        clock.advance(by: RemoteDesktop.typePaceSeconds * 10)
    }

    func testAModifierIsHeldUntilTheNextKey() {
        let sender = self.sender()
        sender.barKey(.alt)
        XCTAssertEqual(sender.held, [.alt])
        sender.barKey(.tab)
        XCTAssertEqual(core.calls, ["key VK_MENU down", "key VK_TAB down", "key VK_TAB up", "key VK_MENU up"])
        XCTAssertEqual(reported, [[.alt], []])
    }

    func testASecondPressLetsAModifierGo() {
        let sender = self.sender()
        sender.barKey(.shift)
        sender.barKey(.shift)
        XCTAssertEqual(core.calls, ["key VK_SHIFT down", "key VK_SHIFT up"])
        XCTAssertEqual(sender.held, [])
    }

    func testTextIsTypedOneCharacterAtATimePacedApart() {
        let sender = self.sender()
        sender.type("不用")
        XCTAssertEqual(core.calls, ["text 不"])
        clock.advance(by: RemoteDesktop.typePaceSeconds - 0.001)
        XCTAssertEqual(core.calls, ["text 不"])
        clock.advance(by: 0.001)
        XCTAssertEqual(core.calls, ["text 不", "text 用"])
    }

    func testAnEmojiIsTypedAsOneCharacter() {
        sender().type("a😀b")
        drain()
        XCTAssertEqual(core.calls, ["text a", "text 😀", "text b"])
    }

    func testABackspaceAfterAWordWaitsForTheWord() {
        let sender = self.sender()
        sender.type("下载")
        sender.press(RemoteDesktopKey.backspace)
        XCTAssertEqual(core.calls, ["text 下"])
        drain()
        XCTAssertEqual(core.calls, ["text 下", "text 载", "key VK_BACK down", "key VK_BACK up"])
    }

    func testAModifierHeldWithOneLetterIsThatKey() {
        let sender = self.sender()
        sender.barKey(.ctrl)
        sender.type("c")
        XCTAssertEqual(core.calls, ["key VK_CONTROL down", "key VK_C down", "key VK_C up", "key VK_CONTROL up"])
    }

    func testALineBreakIsEnterAndATabIsTab() {
        let sender = self.sender()
        sender.type("\n")
        sender.type("\t")
        XCTAssertEqual(core.calls, ["key VK_RETURN down", "key VK_RETURN up", "key VK_TAB down", "key VK_TAB up"])
    }

    func testTextWithAModifierHeldIsTypedAndLetsItGo() {
        let sender = self.sender()
        sender.barKey(.ctrl)
        sender.type("你好")
        drain()
        XCTAssertEqual(core.calls, ["key VK_CONTROL down", "text 你", "text 好", "key VK_CONTROL up"])
    }

    func testPasteSendsTheClipboardThenCtrlV() {
        sender().paste("copied")
        XCTAssertEqual(
            core.calls,
            ["clipboard copied", "key VK_CONTROL down", "key VK_V down", "key VK_V up", "key VK_CONTROL up"])
    }

    func testChineseToALinuxHostIsOnePasteWithShiftInsert() {
        sender(platformOs: "linux").type("我在测试输入法")
        drain()
        XCTAssertEqual(
            core.calls,
            [
                "clipboard 我在测试输入法", "key VK_SHIFT down", "key VK_INSERT down", "key VK_INSERT up",
                "key VK_SHIFT up",
            ])
    }

    func testAsciiToALinuxHostIsTyped() {
        sender(platformOs: "linux").type("ok")
        drain()
        XCTAssertEqual(core.calls, ["text o", "text k"])
    }

    func testChineseToAWindowsHostIsTyped() {
        sender(platformOs: "windows").type("你好")
        drain()
        XCTAssertEqual(core.calls, ["text 你", "text 好"])
    }

    func testAPasteToALinuxHostKeepsItsPlaceAmongKeys() {
        let sender = self.sender(platformOs: "linux")
        sender.type("ab")
        sender.type("中文")
        sender.press(RemoteDesktopKey.backspace)
        drain()
        XCTAssertEqual(
            core.calls,
            [
                "text a", "text b", "clipboard 中文", "key VK_SHIFT down", "key VK_INSERT down", "key VK_INSERT up",
                "key VK_SHIFT up", "key VK_BACK down", "key VK_BACK up",
            ])
    }

    func testAModifierHeldWithOneLetterToALinuxHostIsThatKey() {
        let sender = self.sender(platformOs: "linux")
        sender.barKey(.ctrl)
        sender.type("c")
        XCTAssertEqual(core.calls, ["key VK_CONTROL down", "key VK_C down", "key VK_C up", "key VK_CONTROL up"])
    }

    func testAnEmptyPasteSendsNothing() {
        sender().paste("")
        XCTAssertEqual(core.calls, [])
    }

    func testAClosedSenderSendsWhatWasQueuedAndNothingMore() {
        let sender = self.sender()
        sender.type("ab")
        sender.close()
        sender.type("c")
        drain()
        XCTAssertEqual(core.calls, ["text a", "text b"])
    }
}
