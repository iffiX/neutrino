import Foundation

/// Every hub this phone joined, and this installation's machine id, in one Keychain item. An item that is
/// missing or does not read is no binding and a fresh id.
final class BindingStore {
    private let secrets: SecretStore
    private var held: BindingFile

    /// Called with every binding after each change.
    var onChange: (([HubBinding]) -> Void)?

    /// Read the bindings.
    ///
    /// - Parameter secrets: Where the item lives.
    init(secrets: SecretStore) {
        self.secrets = secrets
        let data = secrets.read(account: Client.bindingsAccount)
        held = data.flatMap { try? JSONDecoder().decode(BindingFile.self, from: $0) } ?? BindingFile()
    }

    /// Every binding, in the order joined.
    var bindings: [HubBinding] { held.bindings }

    /// This installation's id: a uuid4 hex made on the first read and kept.
    var machineId: String {
        if held.machineId.isEmpty {
            var next = held
            next.machineId = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
            try? write(next)
            if held.machineId.isEmpty { held = next }
        }
        return held.machineId
    }

    /// One binding.
    ///
    /// - Parameter id: The binding's id.
    /// - Returns: The binding, or nil.
    func get(_ id: String) -> HubBinding? {
        held.bindings.first { $0.id == id }
    }

    /// Keep one binding; one with the same id is replaced where it stands.
    ///
    /// - Parameter binding: The binding.
    /// - Throws: `ClientError.refused` with `client_internal {error}` when the item cannot be written.
    func put(_ binding: HubBinding) throws {
        var next = held
        if let index = next.bindings.firstIndex(where: { $0.id == binding.id }) {
            next.bindings[index] = binding
        } else {
            next.bindings.append(binding)
        }
        try write(next)
    }

    /// Change one binding; an id nobody holds changes nothing.
    ///
    /// - Parameters:
    ///   - id: The binding's id.
    ///   - change: What to make of it.
    /// - Returns: The binding as kept, or nil when no binding has that id.
    /// - Throws: `ClientError.refused` with `client_internal {error}` when the item cannot be written.
    @discardableResult
    func update(_ id: String, _ change: (inout HubBinding) -> Void) throws -> HubBinding? {
        guard var binding = get(id) else { return nil }
        let before = binding
        change(&binding)
        if binding != before { try put(binding) }
        return binding
    }

    /// Drop one binding.
    ///
    /// - Parameter id: The binding's id.
    /// - Throws: `ClientError.refused` with `client_internal {error}` when the item cannot be written.
    func remove(_ id: String) throws {
        var next = held
        next.bindings.removeAll { $0.id == id }
        try write(next)
    }

    /// Keep one binding per hub id, the one joined last.
    ///
    /// - Returns: The bindings dropped, in the order joined; empty when no hub id is held twice, and the item is then
    ///   not written.
    /// - Throws: `ClientError.refused` with `client_internal {error}` when the item cannot be written.
    func dropRepeatedHubs() throws -> [HubBinding] {
        var last: [String: Int] = [:]
        for (index, binding) in held.bindings.enumerated() { last[binding.hubId] = index }
        var next = held
        next.bindings = []
        var dropped: [HubBinding] = []
        for (index, binding) in held.bindings.enumerated() {
            if binding.hubId.isEmpty || last[binding.hubId] == index {
                next.bindings.append(binding)
            } else {
                dropped.append(binding)
            }
        }
        if !dropped.isEmpty { try write(next) }
        return dropped
    }

    private func write(_ next: BindingFile) throws {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        let data: Data
        do {
            data = try encoder.encode(next)
        } catch {
            throw ClientError.refusal(Channel.codeClientInternal, ["error": "\(error)"])
        }
        try secrets.write(account: Client.bindingsAccount, data: data)
        let isChanged = next.bindings != held.bindings
        held = next
        if isChanged { onChange?(held.bindings) }
    }
}
