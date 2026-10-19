import XCTest

@testable import Neutrino

final class EnrollmentLinkTests: XCTestCase {
    /// A client link Python's zlib wrote at level 9, as the hub does.
    private let hubLink =
        "neutrino://enroll/eNqlkE9PxCAQxb8L54aFttHKzTUejNe9bZqGltE2pYD8WdNs-t0dVmPU7M1wYX7MvPeYM0le"  // scan: allow
        + "ByKOZIzRBbHb8buS8puGcsYoF01dV6T4fjyWjHGh-kYI3n4-tgWJdgZDBDk8PTw_HniZJ14cgvv9_w7qeKsBlQY9gY"  // scan: allow
        + "lY2xN4Ldcc-Uyct6dJgccGA7GfvMKOADG5boYV6Yz1Io18hQXHO_wrwpzuTeXAY-rp1yAdtE15HFknlfIQ0IPkLTQN"  // scan: allow
        + "xVWQrfhlCDKsccIrOliVM6JRkhprlHy3fu6MXDI3P1CAwUNEGBA6uCjFweFqS1ZlG17RW8E54-xKFsquJbFxvMT400"  // scan: allow
        + "1LWtGabO32Ac4FkKw"  // scan: allow

    /// A device link, which a client refuses.
    private let deviceLink =
        "neutrino://enroll/eNqrViotyilWsopWyigpKSi20tc3tDTSMzSz0DM0MNAztLIwMTFWitVRKsnPTs1TslIKUdJR"  // scan: allow
        + "SisAMhKTKINAc4ryc1JBJqWn5pUo1QIAf80szg"  // scan: allow

    func testAHubsLinkReadsWithEveryAddressTheTicketThePinAndTheOverlaysHubAddresses() throws {
        let link = try EnrollmentLink.parse(hubLink)
        XCTAssertEqual(link.urls, ["https://192.168.100.1:8443", "https://[2001:db8::1]:8443"])
        XCTAssertEqual(link.ticket, "TICKET123")
        XCTAssertEqual(link.fingerprint, String(repeating: "ab", count: 32))
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
            "urls": .array([.string("https://10.0.0.2:8443/")]), "token": .string("t"),
            "fp": .string(Samples.fingerprint), "role": .string("client"),
        ])
        XCTAssertEqual(try EnrollmentLink.parse(made).urls, ["https://10.0.0.2:8443"])
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

    func testALinkWithoutAPinIsLinkIncomplete() {
        let made = Samples.link([
            "urls": .array([.string("https://10.0.0.2:8443")]), "token": .string("t"), "role": .string("client"),
        ])
        XCTAssertThrowsError(try EnrollmentLink.parse(made)) { error in
            XCTAssertEqual((error as? ClientError)?.code, "link_incomplete")
        }
    }
}
