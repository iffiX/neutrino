import XCTest

@testable import Neutrino

final class ChannelInboundTests: XCTestCase {
    func testAWelcomeReadsAsTheHubsIdentityCard() {
        XCTAssertEqual(
            ChannelInbound.decode(Samples.welcome.jsonText),
            .welcome(
                ChannelWelcome(
                    protocolNumber: 4, role: "hub", id: "hub-1", name: "Home", software: "neutrino_hub/0.6.0")))
    }

    func testAStateReadsEverySectionAndTheThreeServersAddresses() {
        let frame = Samples.state(
            hash: "h2",
            [
                "is_disabled": .bool(false),
                "urls": .array([.string("https://192.168.1.1:8443/"), .string("https://relay.example:2222")]),
                "ssh_relay_url": .string("https://relay.example:2222"),
                "sakurafrp_url": .string("https://frp.example:4000"),
                "openfrp_url": .string(""),
                "overlays": .array([.object(["provider": .string("easytier"), "hub_address": .string("10.0.0.1")])]),
                "terminals": .array([
                    .object([
                        "device_id": .string("d1"), "name": .string("box"), "is_online": .bool(true),
                        "sessions": .array([.object(["session_id": .string("s1"), "is_shared": .bool(true)])]),
                    ])
                ]),
                "reached_through": .string("sakurafrp"),
                "unknown_section": .string("ignored"),
            ])
        guard case .state(let state)? = ChannelInbound.decode(frame.jsonText) else {
            return XCTFail("a state frame did not read")
        }
        XCTAssertEqual(state.hash, "h2")
        XCTAssertEqual(state.urls, ["https://192.168.1.1:8443", "https://relay.example:2222"])
        XCTAssertEqual(
            state.serverPaths, ["https://relay.example:2222": .sshRelay, "https://frp.example:4000": .sakurafrp])
        XCTAssertEqual(state.overlays, [ChannelOverlay(provider: "easytier", hubAddress: "10.0.0.1")])
        XCTAssertEqual(state.terminals.first?.sessions.first?.isShared, true)
        XCTAssertEqual(state.reachedThrough, "sakurafrp")
    }

    func testTheStatesSectionsThisAppReadsAreTheGoldens() {
        let read: Set = [
            "hash", "is_disabled", "services", "urls", "ssh_relay_url", "sakurafrp_url", "openfrp_url", "overlays",
            "terminals", "is_panel_allowed", "reached_through",
        ]
        XCTAssertEqual(read.subtracting(GoldenSchema.properties("ChannelClientState")), [])
    }

    func testStreamFramesNameTheirStream() {
        XCTAssertEqual(
            ChannelInbound.decode(#"{"type":"close","stream":3,"code":"permission_denied","params":{"kind":"web"}}"#),
            .close(stream: 3, code: "permission_denied", params: ["kind": .string("web")]))
        XCTAssertEqual(
            ChannelInbound.decode(#"{"type":"credit","stream":5,"bytes":1024}"#), .credit(stream: 5, bytes: 1024))
        XCTAssertNil(ChannelInbound.decode(#"{"type":"credit","bytes":1024}"#))
    }

    func testARefusalReadsAsItsCodeAndParams() {
        XCTAssertEqual(
            ChannelInbound.decode(#"{"type":"refused","code":"protocol_too_old","params":{"peer":3,"hub":4,"min":4}}"#),
            .refused(.refused(code: "protocol_too_old", params: ["peer": .int(3), "hub": .int(4), "min": .int(4)])))
    }

    func testTextThatIsNoObjectDoesNotReadAndAnUnknownTypeIsKept() {
        XCTAssertNil(ChannelInbound.decode("[1,2]"))
        XCTAssertNil(ChannelInbound.decode("nope"))
        XCTAssertEqual(ChannelInbound.decode(#"{"type":"news"}"#), .unknown("news"))
    }
}
