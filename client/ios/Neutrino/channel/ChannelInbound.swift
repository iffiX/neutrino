import Foundation

/// One frame the hub sent on the control stream, read tolerantly: an unknown field is ignored.
enum ChannelInbound: Equatable {
    /// The hub's identity card.
    case welcome(ChannelWelcome)
    /// The hub turned this binding away; the session ends after it.
    case refused(ClientError)
    /// What is to be true for this phone.
    case state(ChannelClientState)
    /// The answer to a question this phone asked with a frame: its mark, and its params or its refusal.
    case reply(request: String, result: Result<[String: JSONValue], ClientError>)
    /// The answer to a ping of this phone's.
    case pong(nonce: String)
    /// A frame this build does not read, by its `type`.
    case unknown(String)

    /// Read one frame.
    ///
    /// - Parameter frame: The frame as the transport passed it on.
    /// - Returns: The frame.
    static func decode(_ frame: [String: JSONValue]) -> ChannelInbound {
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
        case ChannelFrames.typeReply:
            let code = frame.text("code")
            let params = frame.object("params")
            return .reply(
                request: frame.text("request"),
                result: code.isEmpty ? .success(params) : .failure(.refused(code: code, params: params)))
        case ChannelFrames.typePong:
            return .pong(nonce: frame.text("nonce"))
        default:
            return .unknown(type)
        }
    }
}
