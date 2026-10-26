import Foundation

/// Every frame this phone writes on a hub's control stream, and the fields of the transport's `join`, each with
/// exactly the fields its protocol defines; a frame's `type` is its name.
enum ChannelFrames {
    /// This phone's identity card, the first frame of a session.
    static let typeHello = "hello"

    /// The hub's identity card.
    static let typeWelcome = "welcome"

    /// A refusal; the hub ends the session after it.
    static let typeRefused = "refused"

    /// What is to be true.
    static let typeState = "state"

    /// What is true.
    static let typeReport = "report"

    /// This phone's own round trip probe.
    static let typePing = "ping"

    /// The answer to a ping, with its nonce.
    static let typePong = "pong"

    /// A question for one entry's material, or the panel's sign-in.
    static let typeService = "service"

    /// Whether a kept shell stays and whether others can attach to it.
    static let typePersist = "persist"

    /// Ends a kept shell.
    static let typeStopSession = "stop_session"

    /// The answer to a `service`, `persist` or `stop_session`.
    static let typeReply = "reply"

    /// The first frame of a session: this phone's identity card.
    ///
    /// - Parameters:
    ///   - binding: The binding the session is for.
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

    /// A round trip probe; the hub's transport echoes its nonce in a `pong`.
    ///
    /// - Parameter nonce: The mark of this ping, at most 64 characters.
    /// - Returns: The frame.
    static func ping(nonce: String) -> [String: JSONValue] {
        ["type": .string(typePing), "nonce": .string(nonce)]
    }

    /// A question for the material one published entry takes, or for the panel's sign-in.
    ///
    /// - Parameters:
    ///   - request: This phone's mark of the question, which the reply names.
    ///   - args: `{id}` for an entry, `{is_panel: true}` for the panel.
    /// - Returns: The frame.
    static func service(request: String, args: [String: JSONValue]) -> [String: JSONValue] {
        var frame = args
        frame["type"] = .string(typeService)
        frame["request"] = .string(request)
        return frame
    }

    /// Whether a kept shell stays when its last stream closes, and whether others can attach to it.
    ///
    /// - Parameters:
    ///   - request: This phone's mark of the question.
    ///   - sessionId: The session.
    ///   - isPersistent: Whether it outlives every window.
    ///   - isShared: Whether every client with terminal rights on the machine lists it.
    /// - Returns: The frame.
    static func persist(request: String, sessionId: String, isPersistent: Bool, isShared: Bool) -> [String: JSONValue] {
        [
            "type": .string(typePersist),
            "request": .string(request),
            "session_id": .string(sessionId),
            "is_persistent": .bool(isPersistent),
            "is_shared": .bool(isShared),
        ]
    }

    /// Ends a kept shell and every program in it.
    ///
    /// - Parameters:
    ///   - request: This phone's mark of the question.
    ///   - sessionId: The session.
    /// - Returns: The frame.
    static func stopSession(request: String, sessionId: String) -> [String: JSONValue] {
        ["type": .string(typeStopSession), "request": .string(request), "session_id": .string(sessionId)]
    }

    /// The `join` frame's body, which the transport sends on the round's winner.
    ///
    /// - Parameters:
    ///   - ticket: The link's ticket.
    ///   - machine: This phone.
    /// - Returns: The body: `{ticket, role, protocol, machine_id, name, software, platform}`.
    static func join(ticket: String, machine: ClientMachine) -> [String: JSONValue] {
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
}
