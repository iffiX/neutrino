import Foundation

@testable import Neutrino

/// A socket a test drives: it records what was sent and delivers the events the test gives it.
final class FakeChannelSocket: ChannelSocket {
    let url: String
    var onEvent: ((ChannelSocketEvent) -> Void)?
    private(set) var texts: [String] = []
    private(set) var binaries: [Data] = []
    private(set) var closedCode: Int?

    init(url: String) {
        self.url = url
    }

    var isClosed: Bool { closedCode != nil }

    /// The text frames sent, read as JSON objects.
    var frames: [[String: JSONValue]] { texts.compactMap { JSONValue.parseObject($0) } }

    /// The types of the text frames sent, in order.
    var frameTypes: [String] { frames.map { $0.text("type") } }

    @discardableResult
    func sendText(_ text: String) -> Bool {
        guard !isClosed else { return false }
        texts.append(text)
        return true
    }

    @discardableResult
    func sendBytes(_ bytes: Data) -> Bool {
        guard !isClosed else { return false }
        binaries.append(bytes)
        return true
    }

    func close(code: Int) {
        if closedCode == nil { closedCode = code }
        onEvent = nil
    }

    /// Deliver one event, as the transport would.
    ///
    /// - Parameter event: The event.
    func deliver(_ event: ChannelSocketEvent) {
        onEvent?(event)
    }

    /// Deliver one text frame built from an object.
    ///
    /// - Parameter frame: The frame.
    func deliver(frame: [String: JSONValue]) {
        onEvent?(.text(frame.jsonText))
    }
}
