import XCTest

@testable import Neutrino

final class ChannelInboundTests: XCTestCase {
    func testAWelcomeReadsAsTheHubsIdentityCard() {
        XCTAssertEqual(
            ChannelInbound.decode(Samples.welcome),
            .welcome(
                ChannelWelcome(
                    protocolNumber: 4, role: "hub", id: "hub-1", name: "Home", software: "neutrino_hub/0.6.0")))
    }

    func testAStateReadsEverySectionAndTheThreeServersAddresses() {
        let frame = Samples.state(
            hash: "h2",
            [
                "is_disabled": .bool(false),
                "urls": .array([.string("tcp://192.168.1.1:8443/"), .string("tcp://relay.example:2222")]),
                "ssh_relay_url": .string("tcp://relay.example:2222"),
                "sakurafrp_url": .string("tcp://frp.example:4000"),
                "openfrp_url": .string(""),
                "overlays": .array([.object(["provider": .string("easytier"), "hub_address": .string("10.0.0.1")])]),
                "terminals": .array([
                    .object([
                        "device_id": .string("d1"), "name": .string("box"), "is_online": .bool(true),
                        "accounts": .array([.string("iffi"), .string("lab")]),
                        "sessions": .array([
                            .object([
                                "session_id": .string("s1"), "is_shared": .bool(true), "account": .string("lab"),
                            ])
                        ]),
                    ])
                ]),
                "apps": .array([
                    .object([
                        "id": .string("gitea_d1"), "title": .string("Gitea"), "source": .string("module"),
                        "device_id": .string("d1"), "device_name": .string("box"),
                        "local_name": .string("gitea.box.localhost"),
                    ])
                ]),
                "services": .array([
                    .object([
                        "id": .string("gitea_d1_ssh"), "type": .string("port"), "title": .string("Gitea"),
                        "payload": .object(["port": .int(22), "protocol": .string("tcp")]), "source": .string("module"),
                        "app_id": .string("gitea_d1"), "name": .string("ssh"), "local_port": .int(30418),
                    ])
                ]),
                "reached_through": .string("sakurafrp"),
                "unknown_section": .string("ignored"),
            ])
        guard case .state(let state) = ChannelInbound.decode(frame) else {
            return XCTFail("a state frame did not read")
        }
        XCTAssertEqual(state.hash, "h2")
        XCTAssertEqual(state.urls, ["tcp://192.168.1.1:8443", "tcp://relay.example:2222"])
        XCTAssertEqual(
            state.serverPaths, ["tcp://relay.example:2222": .sshRelay, "tcp://frp.example:4000": .sakurafrp])
        XCTAssertEqual(state.overlays, [ChannelOverlay(provider: "easytier", hubAddress: "10.0.0.1")])
        XCTAssertEqual(state.terminals.first?.accounts, ["iffi", "lab"])
        XCTAssertEqual(state.terminals.first?.sessions.first?.account, "lab")
        XCTAssertEqual(state.apps.first?.localName, "gitea.box.localhost")
        XCTAssertEqual(state.services.first?.appId, "gitea_d1")
        XCTAssertEqual(state.services.first?.localPort, 30418)
        XCTAssertEqual(state.services.first?.protocol, "tcp")
        XCTAssertEqual(state.reachedThrough, "sakurafrp")
    }

    func testTheStatesSectionsThisAppReadsAreTheGoldens() {
        let read: Set = [
            "hash", "is_disabled", "services", "apps", "urls", "ssh_relay_url", "sakurafrp_url", "openfrp_url",
            "overlays", "terminals", "is_panel_allowed", "reached_through",
        ]
        XCTAssertEqual(read, GoldenSchema.properties("ChannelClientState"))
        XCTAssertTrue(GoldenSchema.properties("ChannelApp").isSuperset(of: ["local_name", "source"]))
        XCTAssertTrue(GoldenSchema.properties("ChannelServiceEntry").isSuperset(of: ["app_id", "name", "local_port"]))
        XCTAssertTrue(GoldenSchema.properties("ChannelTerminal").contains("accounts"))
    }

    func testAReplyIsItsRequestWithItsParamsOrItsRefusal() {
        XCTAssertEqual(
            ChannelInbound.decode([
                "type": .string("reply"), "request": .string("r1"), "code": .string(""),
                "params": .object(["token": .string("t")]),
            ]),
            .reply(request: "r1", result: .success(["token": .string("t")])))
        XCTAssertEqual(
            ChannelInbound.decode([
                "type": .string("reply"), "request": .string("r2"), "code": .string("vault_locked"),
                "params": .object([:]),
            ]),
            .reply(request: "r2", result: .failure(.refusal("vault_locked"))))
    }

    func testARefusalReadsAsItsCodeAndParams() {
        XCTAssertEqual(
            ChannelInbound.decode([
                "type": .string("refused"), "code": .string("protocol_too_old"),
                "params": .object(["peer": .int(3), "hub": .int(4), "min": .int(4)]),
            ]),
            .refused(.refused(code: "protocol_too_old", params: ["peer": .int(3), "hub": .int(4), "min": .int(4)])))
    }

    func testAPongAndAnUnknownTypeRead() {
        XCTAssertEqual(ChannelInbound.decode(["type": .string("pong"), "nonce": .string("n7")]), .pong(nonce: "n7"))
        XCTAssertEqual(ChannelInbound.decode(["type": .string("news")]), .unknown("news"))
    }
}
