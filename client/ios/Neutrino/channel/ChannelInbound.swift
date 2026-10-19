import Foundation

/// One text frame the hub sent, read tolerantly: an unknown field is ignored.
enum ChannelInbound: Equatable {
    /// The hub's identity card.
    case welcome(ChannelWelcome)
    /// The hub turned this binding away; close 4000 follows.
    case refused(ClientError)
    /// What is to be true for this phone.
    case state(ChannelClientState)
    /// A stream this phone opened has ended: its id, the refusal's code or empty, and the params.
    case close(stream: UInt32, code: String, params: [String: JSONValue])
    /// The hub takes this many more bytes on a stream.
    case credit(stream: UInt32, bytes: Int)
    /// The hub opened a stream; a client serves none.
    case open(stream: UInt32, kind: String)
    /// The hub's answer to a ping of this phone's.
    case pong(nonce: String)
    /// A frame this build does not read, by its `type`.
    case unknown(String)

    /// Read one text frame.
    ///
    /// - Parameter text: The frame's text.
    /// - Returns: The frame, or nil when the text is not a JSON object or a stream frame names no stream.
    static func decode(_ text: String) -> ChannelInbound? {
        guard let frame = JSONValue.parseObject(text) else { return nil }
        let type = frame.text("type")
        switch type {
        case ChannelFrames.typeWelcome:
            return .welcome(
                ChannelWelcome(
                    protocolNumber: frame.number("protocol") ?? 0,
                    role: frame.text("role"),
                    id: frame.text("id"),
                    name: frame.text("name"),
                    software: frame.text("software")))
        case ChannelFrames.typeRefused:
            return .refused(.refused(code: frame.text("code"), params: frame.object("params")))
        case ChannelFrames.typeState:
            return .state(ChannelClientState.of(frame))
        case ChannelFrames.typeClose:
            guard let stream = streamOf(frame) else { return nil }
            return .close(stream: stream, code: frame.text("code"), params: frame.object("params"))
        case ChannelFrames.typeCredit:
            guard let stream = streamOf(frame), let bytes = frame.number("bytes") else { return nil }
            return .credit(stream: stream, bytes: bytes)
        case ChannelFrames.typeOpen:
            guard let stream = streamOf(frame) else { return nil }
            return .open(stream: stream, kind: frame.text("kind"))
        case ChannelFrames.typePong:
            return .pong(nonce: frame.text("nonce"))
        default:
            return .unknown(type)
        }
    }

    private static func streamOf(_ frame: [String: JSONValue]) -> UInt32? {
        guard let stream = frame.number("stream"), stream >= 0 else { return nil }
        return UInt32(exactly: stream)
    }
}
