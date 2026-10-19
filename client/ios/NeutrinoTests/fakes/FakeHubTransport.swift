import Foundation

@testable import Neutrino

/// A transport whose sockets and requests a test answers by hand.
final class FakeHubTransport: HubTransport {
    /// Every socket opened, in order.
    private(set) var sockets: [FakeChannelSocket] = []

    /// Every request posted, in order, with the completion that answers it.
    private(set) var posts: [FakeHubPost] = []

    func post(
        baseUrl: String, path: String, fingerprint: String, body: [String: JSONValue],
        completion: @escaping (Result<[String: JSONValue], ClientError>) -> Void
    ) {
        posts.append(FakeHubPost(baseUrl: baseUrl, path: path, body: body, completion: completion))
    }

    func connect(baseUrl: String, fingerprint: String) -> ChannelSocket {
        let socket = FakeChannelSocket(url: baseUrl)
        sockets.append(socket)
        return socket
    }

    /// The sockets opened to one address, in order.
    ///
    /// - Parameter url: The address.
    /// - Returns: The sockets.
    func sockets(to url: String) -> [FakeChannelSocket] {
        sockets.filter { $0.url == url }
    }
}
