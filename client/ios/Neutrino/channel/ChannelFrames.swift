import Foundation

/// Every frame and body this phone writes on the channel, each with exactly the fields its protocol defines.
enum ChannelFrames {
    /// The first frame up: the identity card.
    static let typeHello = "hello"

    /// The hub's identity card.
    static let typeWelcome = "welcome"

    /// A refusal, then close 4000.
    static let typeRefused = "refused"

    /// What is to be true.
    static let typeState = "state"

    /// What is true.
    static let typeReport = "report"

    /// A stream begins.
    static let typeOpen = "open"

    /// A stream ends.
    static let typeClose = "close"

    /// The sender may send more.
    static let typeCredit = "credit"

    /// This phone's own round trip probe.
    static let typePing = "ping"

    /// The hub's answer to a ping, with its nonce.
    static let typePong = "pong"

    /// The first frame up: this phone's identity card with the binding's token.
    ///
    /// - Parameters:
    ///   - binding: The binding the socket is for.
    ///   - machine: This phone.
    /// - Returns: The frame.
    static func hello(binding: HubBinding, machine: ClientMachine) -> [String: JSONValue] {
        [
            "type": .string(typeHello),
            "protocol": .int(Channel.PROTOCOL),
            "role": .string(Client.role),
            "id": .string(binding.boundId),
            "name": .string(binding.name.isEmpty ? machine.hostname : binding.name),
            "software": .string(machine.software),
            "token": .string(binding.token),
        ]
    }

    /// What is true of this phone, and the hash of the state held.
    ///
    /// - Parameters:
    ///   - stateHash: The hash of the last state taken, empty before the first.
    ///   - machine: This phone.
    ///   - isRefresh: Whether a person pressed refresh, which asks for the whole state whatever its hash.
    /// - Returns: The frame.
    static func report(stateHash: String, machine: ClientMachine, isRefresh: Bool = false) -> [String: JSONValue] {
        [
            "type": .string(typeReport),
            "state_hash": .string(stateHash),
            "is_refresh": .bool(isRefresh),
            "machine": .object([
                "hostname": .string(machine.hostname),
                "platform": .object(machine.platform),
                "os_machine_id": .string(""),
            ]),
        ]
    }

    /// A stream begins: the request, its arguments beside `stream` and `kind`.
    ///
    /// - Parameters:
    ///   - stream: The stream's id.
    ///   - kind: The stream's kind.
    ///   - args: The kind's own arguments.
    /// - Returns: The frame.
    static func open(stream: UInt32, kind: String, args: [String: JSONValue]) -> [String: JSONValue] {
        var frame = args
        frame["type"] = .string(typeOpen)
        frame["stream"] = .int(Int(stream))
        frame["kind"] = .string(kind)
        return frame
    }

    /// A stream ends from this side.
    ///
    /// - Parameters:
    ///   - stream: The stream's id.
    ///   - code: The refusal's code, empty for a result.
    ///   - params: The result, or the refusal's parameters.
    /// - Returns: The frame.
    static func close(stream: UInt32, code: String = "", params: [String: JSONValue] = [:]) -> [String: JSONValue] {
        ["type": .string(typeClose), "stream": .int(Int(stream)), "code": .string(code), "params": .object(params)]
    }

    /// The hub may send this many more bytes on a stream.
    ///
    /// - Parameters:
    ///   - stream: The stream's id.
    ///   - bytes: The grant.
    /// - Returns: The frame.
    static func credit(stream: UInt32, bytes: Int) -> [String: JSONValue] {
        ["type": .string(typeCredit), "stream": .int(Int(stream)), "bytes": .int(bytes)]
    }

    /// A round trip probe; the hub echoes its nonce in a `pong`.
    ///
    /// - Parameter nonce: The mark of this ping, at most 64 characters.
    /// - Returns: The frame.
    static func ping(nonce: String) -> [String: JSONValue] {
        ["type": .string(typePing), "nonce": .string(nonce)]
    }

    /// The body of `POST /api/channel/join`.
    ///
    /// - Parameters:
    ///   - ticket: The link's ticket.
    ///   - machine: This phone.
    /// - Returns: The body.
    static func joinRequest(ticket: String, machine: ClientMachine) -> [String: JSONValue] {
        [
            "ticket": .string(ticket),
            "role": .string(Client.role),
            "protocol": .int(Channel.PROTOCOL),
            "machine_id": .string(machine.machineId),
            "name": .string(machine.hostname),
            "software": .string(machine.software),
            "platform": .object(machine.platform),
        ]
    }

    /// The body of `POST /api/channel/leave`.
    ///
    /// - Parameter binding: The binding being ended.
    /// - Returns: The body.
    static func leaveRequest(binding: HubBinding) -> [String: JSONValue] {
        ["id": .string(binding.boundId), "token": .string(binding.token)]
    }

    /// One binary frame: the big-endian stream id, then the bytes.
    ///
    /// - Parameters:
    ///   - stream: The stream's id.
    ///   - bytes: The bytes.
    /// - Returns: The frame.
    static func binary(stream: UInt32, bytes: Data) -> Data {
        var frame = Data(capacity: Channel.streamIdBytes + bytes.count)
        frame.append(UInt8(truncatingIfNeeded: stream >> 24))
        frame.append(UInt8(truncatingIfNeeded: stream >> 16))
        frame.append(UInt8(truncatingIfNeeded: stream >> 8))
        frame.append(UInt8(truncatingIfNeeded: stream))
        frame.append(bytes)
        return frame
    }
}
