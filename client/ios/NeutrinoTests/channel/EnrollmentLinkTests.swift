import XCTest

@testable import Neutrino

final class EnrollmentLinkTests: XCTestCase {
    /// A client link Python's zlib wrote at level 9, as the hub does.
    private let hubLink =
        "neutrino://enroll/eNqlkDFvgzAQhf-L58jxAWpdr1WHqmu2CCGDrw3C2NQ2qVDEf-85ZGirbBUL993de8"  // scan: allow
        + "93YXOwkakjS92k9nt4Kjg8SA5CcFCyqkq2u7WOhRCgTCuVgnpr1dTzAzqm2OH1-e3lAEWeH3Ahotv_fSQUvE"  // scan: allow
        + "VS6myPLlHtzxisXnLeC5uCP_cGAw04TG0fDE1ETPPUbAEGqkft9AeOtN7QQwkSe_80OfFpbvltkXfWz3mdWK"  // scan: allow
        + "ONCRjJg-UjSMnpEmzd_TJEHZfU0y85eJMzktGsLdUk-eXD0Dg9Zu5-oIhdwEQwEpzwqrTdthBltoGSPyoAAe"  // scan: allow
        + "JOFi7uJfHpdI3xZ5oXvOQVW-v1G2n0l0c"  // scan: allow

    /// A device link, which a client refuses.
    private let deviceLink =
        "neutrino://enroll/eNqrViotyilWsopWKkkusNLXN7Q00jM0s9AzNDDQM7SyMDExVorVUSrJz07NU7JSCl"  // scan: allow
        + "HSUcpOrQSyEpMog0CDivJzUkEmpafmlSjVAgA33ixV"  // scan: allow

    func testAHubsLinkReadsWithEveryAddressTheTicketTheHubsKeyAndTheOverlaysHubAddresses() throws {
        let link = try EnrollmentLink.parse(hubLink)
        XCTAssertEqual(link.urls, ["tcp://192.168.100.1:8443", "tcp://[2001:db8::1]:8443"])
        XCTAssertEqual(link.ticket, "TICKET123")
        XCTAssertEqual(link.hubKey, String(repeating: "ab", count: 32))
        XCTAssertEqual(
            link.overlays,
            [
                ChannelOverlay(provider: "netbird", hubAddress: "100.88.0.1"),
                ChannelOverlay(provider: "easytier", hubAddress: "10.0.0.1"),
            ])
    }

    func testTheBarePayloadReadsAsTheLink() throws {
        let payload = String(hubLink.dropFirst(Channel.linkPrefix.count))
        XCTAssertEqual(try EnrollmentLink.parse("  \(payload)\n"), try EnrollmentLink.parse(hubLink))
    }

    func testAScannedAndAPastedLinkAreOnePath() throws {
        let made = Samples.link([
            "urls": .array([.string("tcp://10.0.0.2:8443/")]), "token": .string("t"),
            "key": .string(Samples.hubKey), "role": .string("client"),
        ])
        XCTAssertEqual(try EnrollmentLink.parse(made).urls, ["tcp://10.0.0.2:8443"])
    }

    func testADevicesLinkIsRefusedNamingItsRole() {
        XCTAssertThrowsError(try EnrollmentLink.parse(deviceLink)) { error in
            XCTAssertEqual(error as? ClientError, .refusal("link_not_for_client", ["role": "agent"]))
        }
    }

    func testNothingIsLinkMissing() {
        XCTAssertThrowsError(try EnrollmentLink.parse("   ")) { error in
            XCTAssertEqual((error as? ClientError)?.code, "link_missing")
        }
    }

    func testSomethingElseIsLinkUnreadable() {
        for text in ["https://example.com", "neutrino://enroll/!!!", "neutrino://enroll/aGVsbG8"] {
            XCTAssertThrowsError(try EnrollmentLink.parse(text)) { error in
                XCTAssertEqual((error as? ClientError)?.code, "link_unreadable", text)
            }
        }
    }

    func testALinkCutShortIsLinkUnreadable() {
        XCTAssertThrowsError(try EnrollmentLink.parse(String(hubLink.dropLast(12)))) { error in
            XCTAssertEqual((error as? ClientError)?.code, "link_unreadable")
        }
    }

    func testALinkWithNoHubKeyIsIncomplete() {
        for pin: [String: JSONValue] in [[:], ["fp": .string(Samples.hubKey)], ["key": .string("abcd")]] {
            var object: [String: JSONValue] = [
                "urls": .array([.string("tcp://10.0.0.2:8443")]), "token": .string("t"), "role": .string("client"),
            ]
            object.merge(pin) { _, new in new }
            XCTAssertThrowsError(try EnrollmentLink.parse(Samples.link(object))) { error in
                XCTAssertEqual((error as? ClientError)?.code, "link_incomplete")
            }
        }
    }
}
