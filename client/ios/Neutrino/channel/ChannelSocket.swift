import Foundation

/// One socket to a hub, opened by a `HubTransport`. Every call and every event runs on the main queue.
protocol ChannelSocket: AnyObject {
    /// Where the socket's events go, in the order they happen; set again by whoever takes the socket over.
    var onEvent: ((ChannelSocketEvent) -> Void)? { get set }

    /// Send one text frame.
    ///
    /// - Parameter text: The frame.
    /// - Returns: False when the socket is gone.
    @discardableResult
    func sendText(_ text: String) -> Bool

    /// Send one binary frame.
    ///
    /// - Parameter bytes: The frame: the stream id, then the bytes.
    /// - Returns: False when the socket is gone.
    @discardableResult
    func sendBytes(_ bytes: Data) -> Bool

    /// Close the socket from this side; no event follows.
    ///
    /// - Parameter code: The close code.
    func close(code: Int)
}

extension ChannelSocket {
    /// Send one frame as JSON text.
    ///
    /// - Parameter frame: The frame.
    /// - Returns: False when the socket is gone.
    @discardableResult
    func send(_ frame: [String: JSONValue]) -> Bool {
        sendText(frame.jsonText)
    }
}
