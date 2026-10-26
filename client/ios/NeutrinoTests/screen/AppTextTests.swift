import XCTest

@testable import Neutrino

final class AppTextTests: XCTestCase {
    private func entry(_ type: String, _ payload: [String: JSONValue], isHealthy: Bool? = nil) -> ChannelServiceEntry {
        var object: [String: JSONValue] = [
            "id": .string("e"), "type": .string(type), "title": .string("A"), "payload": .object(payload),
            "source": .string("module"),
        ]
        if let isHealthy { object["is_healthy"] = .bool(isHealthy) }
        return ChannelServiceEntry.of(.object(object))!
    }

    func testEachEntryShowsItsAddressOnTheLoopback() {
        XCTAssertEqual(
            AppText.localAddress(entry("web", ["url": .string("https://10.0.0.5:3000/login?next=%2F")]), port: 27311),
            "https://127.0.0.1:27311/login?next=%2F")
        XCTAssertEqual(AppText.localAddress(entry("port", ["port": .int(22)]), port: 30418), "127.0.0.1:30418")
        XCTAssertEqual(
            AppText.localAddress(entry("port", ["protocol": .string("udp")]), port: 25001), "127.0.0.1:25001/udp")
    }

    private let words = WordCatalog(words: [
        "ui.entry_kind.web": "Web", "ui.entry_kind.port": "Port", "ui.unhealthy": "Not reachable now",
        "ui.app_source.declared": "declared", "ui.app_provided_by": "from {hub}:{machine} · {source}",
    ])

    func testAnEntrysLineAndKindAreWordedAsOnTheDesktop() {
        XCTAssertEqual(AppText.kind(entry("port", ["protocol": .string("udp")]), words: words), "Port/udp")
        XCTAssertEqual(AppText.kind(entry("web", [:]), words: words), "Web")
        XCTAssertEqual(
            AppText.line(
                entry("web", ["url": .string("http://10.0.0.5:3000/")], isHealthy: false), port: 24001,
                words: words),
            "http://127.0.0.1:24001/ · Not reachable now")
    }

    func testTheProviderLineNamesTheEntrysHostWhenTheHubNamesNoMachine() throws {
        let hub = HubView(binding: Samples.binding)
        let app = try XCTUnwrap(
            ChannelApp.of(.object(["id": .string("a"), "source": .string("declared"), "device_name": .string("box")])))
        let web = entry("web", ["url": .string("http://[fd00::5]:3000/")])
        XCTAssertEqual(AppText.provider(hub, app, [web], words: words), "from Home:box · declared")
        let manual = try XCTUnwrap(ChannelApp.of(.object(["id": .string("a"), "source": .string("other")])))
        XCTAssertEqual(AppText.provider(hub, manual, [web], words: words), "from Home:fd00::5 · ")
        XCTAssertEqual(
            AppText.provider(hub, manual, [entry("port", ["host": .string("10.0.0.9")])], words: words),
            "from Home:10.0.0.9 · ")
    }

    func testTheReasonSaysWhyUseOrConfigureIsDisabled() {
        var hub = HubView(binding: Samples.binding)
        hub.connection = .connected
        let up = entry("web", [:])
        XCTAssertNil(AppText.reasonKey(hub, [up], ForwardRow()))
        XCTAssertEqual(AppText.reasonKey(hub, [up], ForwardRow(isInUse: true)), "ui.reason.disconnect_first")
        XCTAssertEqual(
            AppText.reasonKey(hub, [entry("web", [:], isHealthy: false)], ForwardRow()), "ui.reason.unhealthy")
        hub.waitReason = .disabled
        XCTAssertEqual(AppText.reasonKey(hub, [up], ForwardRow()), "ui.reason.disabled")
    }

    func testTheDotIsGreenWhileAnEntryAnswersAndAmberWhenNoneDoes() {
        let hub = HubView(binding: Samples.binding)
        XCTAssertEqual(
            AppText.tone(hub, [entry("web", [:], isHealthy: false), entry("port", [:])], isBusy: false), .ok)
        XCTAssertEqual(AppText.tone(hub, [entry("web", [:], isHealthy: false)], isBusy: false), .wait)
        XCTAssertEqual(AppText.tone(hub, [entry("web", [:])], isBusy: true), .pulse)
    }
}
