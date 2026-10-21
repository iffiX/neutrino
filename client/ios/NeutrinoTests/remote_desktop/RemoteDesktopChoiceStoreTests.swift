import XCTest

@testable import Neutrino

final class RemoteDesktopChoiceStoreTests: XCTestCase {
    private var defaults = UserDefaults()
    private var suite = ""

    override func setUp() {
        suite = "neutrino.tests.\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suite) ?? .standard
    }

    override func tearDown() {
        defaults.removePersistentDomain(forName: suite)
    }

    func testAnEntryNeverConfiguredIsAutoAndBalanced() {
        XCTAssertEqual(RemoteDesktopChoiceStore(defaults: defaults).choice(of: "b1/r1"), RemoteDesktopChoice())
    }

    func testAKeptChoiceIsReadBackByANewStore() {
        let kept = RemoteDesktopChoice(codec: .vp9, quality: .best)
        RemoteDesktopChoiceStore(defaults: defaults).keep("b1/r1", kept)
        XCTAssertEqual(RemoteDesktopChoiceStore(defaults: defaults).choice(of: "b1/r1"), kept)
    }

    func testLeavingAHubForgetsItsEntriesAlone() {
        let store = RemoteDesktopChoiceStore(defaults: defaults)
        store.keep("b1/r1", RemoteDesktopChoice(codec: .av1, quality: .low))
        store.keep("b2/r1", RemoteDesktopChoice(codec: .vp8, quality: .low))
        store.forget(bindingId: "b1")
        XCTAssertEqual(store.choice(of: "b1/r1"), RemoteDesktopChoice())
        XCTAssertEqual(RemoteDesktopChoiceStore(defaults: defaults).choice(of: "b2/r1").codec, .vp8)
    }
}
