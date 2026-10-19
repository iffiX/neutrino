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

    func testHelloIsTheGoldensHelloWithEveryField() {
        let hello = ChannelFrames.hello(binding: Samples.binding, machine: Samples.machine)
        assertConforms(hello, "ChannelHello")
        XCTAssertEqual(keys(hello), GoldenSchema.properties("ChannelHello"))
        XCTAssertEqual(hello.text("type"), "hello")
        XCTAssertEqual(hello.number("protocol"), Channel.PROTOCOL)
        XCTAssertEqual(hello.text("role"), "client")
        XCTAssertEqual(hello.text("software"), "neutrino_client/0.6.0")
        XCTAssertEqual(hello.text("token"), "secret-token")
    }

    func testReportIsTheGoldensClientReportWithItsMachine() {
        let report = ChannelFrames.report(stateHash: "h1", machine: Samples.machine)
        assertConforms(report, "ChannelClientReport")
        XCTAssertEqual(keys(report), GoldenSchema.properties("ChannelClientReport"))
        XCTAssertEqual(Set(report.object("machine").keys), GoldenSchema.properties("ChannelClientMachine"))
        XCTAssertEqual(
            Set(report.object("machine").object("platform").keys), ["os", "family", "arch", "version"])
        XCTAssertEqual(report.object("machine").object("platform").text("os"), "ios")
    }

    func testARefreshReportSaysSo() {
        XCTAssertTrue(ChannelFrames.report(stateHash: "", machine: Samples.machine, isRefresh: true).flag("is_refresh"))
        XCTAssertFalse(ChannelFrames.report(stateHash: "", machine: Samples.machine).flag("is_refresh"))
    }

    func testOpenIsTheGoldensOpenWithItsArgumentsBeside() {
        let open = ChannelFrames.open(stream: 3, kind: "service", args: ["id": .string("svc")])
        XCTAssertEqual(open.text("id"), "svc")
        var head = open
        head["id"] = nil
        assertConforms(head, "ChannelOpen")
    }

    func testCloseCreditAndPingAreTheGoldens() {
        assertConforms(ChannelFrames.close(stream: 2, code: "kind_unknown"), "ChannelClose")
        assertConforms(ChannelFrames.close(stream: 5), "ChannelClose")
        assertConforms(ChannelFrames.credit(stream: 1, bytes: 1024), "ChannelCredit")
        let ping = ChannelFrames.ping(nonce: "n7")
        assertConforms(ping, "ChannelPing")
        XCTAssertEqual(keys(ping), GoldenSchema.properties("ChannelPing"))
    }

    func testTheJoinAndLeaveBodiesAreTheGoldensWithEveryField() {
        let join = ChannelFrames.joinRequest(ticket: "ticket", machine: Samples.machine)
        assertConforms(join, "ChannelJoinRequest", hasType: false)
        XCTAssertEqual(Set(join.keys), GoldenSchema.properties("ChannelJoinRequest"))
        let leave = ChannelFrames.leaveRequest(binding: Samples.binding)
        assertConforms(leave, "ChannelLeaveRequest", hasType: false)
        XCTAssertEqual(Set(leave.keys), GoldenSchema.properties("ChannelLeaveRequest"))
    }

    func testABinaryFrameIsTheBigEndianStreamIdThenTheBytes() {
        XCTAssertEqual(
            ChannelFrames.binary(stream: 0x0102_0304, bytes: Data([9, 8])), Data([1, 2, 3, 4, 9, 8]))
    }

    func testAValueTheGoldenRefusesIsCaught() {
        var broken = ChannelFrames.credit(stream: 1, bytes: 1)
        broken["type"] = nil
        broken["bytes"] = .string("many")
        XCTAssertEqual(GoldenSchema.problems(.object(broken), "ChannelCredit").count, 1)
    }
}
