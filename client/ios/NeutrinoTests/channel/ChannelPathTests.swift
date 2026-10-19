import XCTest

@testable import Neutrino

final class ChannelPathTests: XCTestCase {
    private let overlays = [
        ChannelOverlay(provider: "netbird", hubAddress: "100.88.0.1"),
        ChannelOverlay(provider: "easytier", hubAddress: "10.0.0.1"),
    ]
    private let servers: [String: ChannelPath] = [
        "https://relay.example:2222": .sshRelay, "https://frp.example:4000": .sakurafrp,
        "https://frp2.example:4001": .openfrp,
    ]
    private let networks = [
        ChannelLocalNetwork(address: [192, 168, 1, 20], prefix: 24),
        ChannelLocalNetwork(address: [0xfd, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2], prefix: 64),
    ]

    private func path(_ url: String) -> ChannelPath {
        ChannelPath.of(url: url, overlays: overlays, serverPaths: servers, localNetworks: networks)
    }

    func testEachCandidateKnowsItsPathBeforeItsHello() {
        XCTAssertEqual(path("https://100.88.0.1:8443"), .netbird)
        XCTAssertEqual(path("https://10.0.0.1:8443"), .easytier)
        XCTAssertEqual(path("https://relay.example:2222"), .sshRelay)
        XCTAssertEqual(path("https://frp.example:4000"), .sakurafrp)
        XCTAssertEqual(path("https://frp2.example:4001"), .openfrp)
        XCTAssertEqual(path("https://192.168.1.1:8443"), .lan)
        XCTAssertEqual(path("https://[fd00::1]:8443"), .lan)
        XCTAssertEqual(path("https://203.0.113.7:8443"), .direct)
        XCTAssertEqual(path("https://hub.example:8443"), .direct)
    }

    func testThePathsRankLanThenDirectThenTheNetworksThenTheServers() {
        XCTAssertEqual(
            [ChannelPath.lan, .direct, .netbird, .easytier, .sshRelay, .sakurafrp, .openfrp].map(\.rank),
            [1, 2, 3, 3, 4, 4, 4])
    }

    func testEachPathIsTheHubsWordForIt() {
        XCTAssertEqual(
            [ChannelPath.lan, .netbird, .easytier, .sshRelay, .direct, .sakurafrp, .openfrp].map(\.rawValue),
            Channel.reachedThrough)
    }
}
