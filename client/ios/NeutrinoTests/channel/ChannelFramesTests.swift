import XCTest

@testable import Neutrino

final class ChannelFramesTests: XCTestCase {
    private func assertConforms(
        _ frame: [String: JSONValue], _ model: String, hasType: Bool = true, file: StaticString = #filePath,
        line: UInt = #line
    ) {
        var body = frame
        if hasType {
            XCTAssertNotNil(frame["type"]?.stringValue, file: file, line: line)
            body["type"] = nil
        }
        XCTAssertEqual(GoldenSchema.problems(.object(body), model), [], file: file, line: line)
    }

    private func keys(_ frame: [String: JSONValue]) -> Set<String> {
        Set(frame.keys).subtracting(["type"])
    }

    func testTheProtocolIsTheGoldens() {
        XCTAssertEqual(GoldenSchema.protocolNumber, Channel.PROTOCOL)
    }

    func testHelloIsTheGoldensHelloWithEveryFieldAndNoToken() {
        let hello = ChannelFrames.hello(binding: Samples.binding, machine: Samples.machine)
        assertConforms(hello, "ChannelHello")
        XCTAssertEqual(keys(hello), GoldenSchema.properties("ChannelHello"))
        XCTAssertEqual(hello.text("type"), "hello")
        XCTAssertEqual(hello.number("protocol"), Channel.PROTOCOL)
        XCTAssertEqual(hello.text("role"), "client")
        XCTAssertEqual(hello.text("software"), "neutrino_client/0.6.0")
        XCTAssertNil(hello["token"])
    }

    func testReportIsTheGoldensClientReportWithItsMachine() {
        let report = ChannelFrames.report(stateHash: "h1", machine: Samples.machine)
        assertConforms(report, "ChannelClientReport")
        XCTAssertEqual(keys(report), GoldenSchema.properties("ChannelClientReport"))
        XCTAssertEqual(Set(report.object("machine").keys), GoldenSchema.properties("ChannelClientMachine"))
        XCTAssertEqual(Set(report.object("machine").object("platform").keys), ["os", "family", "arch"])
        XCTAssertEqual(report.object("machine").object("platform").text("os"), "ios")
    }

    func testARefreshReportSaysSo() {
        XCTAssertTrue(ChannelFrames.report(stateHash: "", machine: Samples.machine, isRefresh: true).flag("is_refresh"))
        XCTAssertFalse(ChannelFrames.report(stateHash: "", machine: Samples.machine).flag("is_refresh"))
    }

    func testPingServicePersistAndStopSessionAreTheGoldens() {
        let ping = ChannelFrames.ping(nonce: "n7")
        assertConforms(ping, "ChannelPing")
        XCTAssertEqual(keys(ping), GoldenSchema.properties("ChannelPing"))
        assertConforms(ChannelFrames.service(request: "r1", args: ["id": .string("rdp_d1")]), "ChannelService")
        assertConforms(ChannelFrames.service(request: "r2", args: ["is_panel": .bool(true)]), "ChannelService")
        let persist = ChannelFrames.persist(request: "r3", sessionId: "s1", isPersistent: true, isShared: false)
        assertConforms(persist, "ChannelPersist")
        XCTAssertEqual(keys(persist), GoldenSchema.properties("ChannelPersist"))
        let stop = ChannelFrames.stopSession(request: "r4", sessionId: "s1")
        assertConforms(stop, "ChannelStopSession")
        XCTAssertEqual(keys(stop), GoldenSchema.properties("ChannelStopSession"))
    }

    func testTheJoinBodyIsTheGoldensJoinWithEveryField() {
        let join = ChannelFrames.join(ticket: "ticket", machine: Samples.machine)
        assertConforms(join, "ChannelJoin", hasType: false)
        XCTAssertEqual(Set(join.keys), GoldenSchema.properties("ChannelJoin"))
    }

    func testAValueTheGoldenRefusesIsCaught() {
        var broken = ChannelFrames.ping(nonce: "n")
        broken["type"] = nil
        broken["nonce"] = .int(7)
        XCTAssertEqual(GoldenSchema.problems(.object(broken), "ChannelPing").count, 1)
    }
}
