import Foundation

/// The one table of local ports, by entry key `<binding>/<entry>`, kept in the app's settings: the numbers the
/// person set in place of the hub's, and the picks of the forwards of no app, each with its protocol. An app entry
/// listens on the person's number, else the hub's; a forward of no app keeps its pick from 20000 to 23999. A
/// number is probed each time its forward is about to listen: an app entry's number another program holds is
/// refused and never moves by itself, and a kept pick another program now holds is picked again.
final class LocalPortTable {
    private let defaults: UserDefaults
    private let isFree: (Int, String, Bool) -> Bool
    private var choices: [String: LocalPortChoice]

    /// Read the table.
    ///
    /// - Parameters:
    ///   - defaults: Where the table is written.
    ///   - isFree: Whether nothing listens on a number now, by the number, the protocol and whether the table
    ///     keeps it.
    init(defaults: UserDefaults, isFree: @escaping (Int, String, Bool) -> Bool = ForwardSocket.isFree) {
        self.defaults = defaults
        self.isFree = isFree
        let data = defaults.data(forKey: Client.settingsKeyLocalPorts)
        choices = data.flatMap { try? JSONDecoder().decode([String: LocalPortChoice].self, from: $0) } ?? [:]
    }

    /// Every entry's kept number.
    var all: [String: LocalPortChoice] { choices }

    /// The number the person set for an app entry.
    ///
    /// - Parameter key: The entry's key.
    /// - Returns: The number, or nil when the entry takes the hub's.
    func number(of key: String) -> Int? {
        guard let choice = choices[key], choice.isFixed else { return nil }
        return choice.port
    }

    /// The number an app entry listens on: the person's, else the hub's.
    ///
    /// - Parameters:
    ///   - key: The entry's key.
    ///   - hubPort: The hub's `local_port` for it.
    /// - Returns: The number.
    func port(of key: String, hubPort: Int) -> Int {
        number(of: key) ?? hubPort
    }

    /// The number an app entry's forward is about to listen on, probed first.
    ///
    /// - Parameters:
    ///   - key: The entry's key.
    ///   - hubPort: The hub's `local_port` for it.
    ///   - protocol: `tcp` or `udp`.
    /// - Returns: The number.
    /// - Throws: `ClientError.refused` with `port_taken {port}` when another program holds it.
    func port(forEntry key: String, hubPort: Int, protocol: String) throws -> Int {
        let port = port(of: key, hubPort: hubPort)
        guard isFree(port, `protocol`, true) else { throw ClientError.refusal("port_taken", ["port": "\(port)"]) }
        return port
    }

    /// The number a forward of no app is about to listen on: its kept pick while nothing else holds it, else the
    /// first free number from 20000 to 23999, kept from then on.
    ///
    /// - Parameters:
    ///   - key: The forward's key.
    ///   - protocol: `tcp` or `udp`.
    /// - Returns: The number.
    /// - Throws: `ClientError.refused` with `forward_failed {detail}` when no number is free.
    func pick(for key: String, protocol: String) throws -> Int {
        let kept = choices[key].flatMap { $0.isFixed || $0.protocol != `protocol` ? nil : $0 }
        if let kept, isFree(kept.port, `protocol`, true) { return kept.port }
        let pick = Forward.pickPorts.first {
            $0 != kept?.port && !isHeld($0, protocol: `protocol`, by: key) && isFree($0, `protocol`, false)
        }
        guard let pick else { throw ClientError.refusal("forward_failed", ["detail": "no local port is free"]) }
        write(key, LocalPortChoice(isFixed: false, port: pick, protocol: `protocol`))
        return pick
    }

    /// Keep the person's number for an app entry, or go back to the hub's.
    ///
    /// - Parameters:
    ///   - key: The entry's key.
    ///   - number: The number, or nil for the hub's.
    ///   - protocol: `tcp` or `udp`.
    ///   - hubNumbers: Every app entry's hub number this phone knows, by key, with its protocol.
    /// - Throws: `ClientError.refused` with `port_range` for a number outside 1024 to 65535, and `port_taken
    ///   {port}` when another entry of the protocol holds it in the table or as its hub number.
    func configure(
        _ key: String, number: Int?, protocol: String, hubNumbers: [String: (port: Int, protocol: String)]
    ) throws {
        guard let number else {
            choices[key] = nil
            save()
            return
        }
        guard Forward.fixedPorts.contains(number) else { throw ClientError.refusal("port_range") }
        let isHubHeld = hubNumbers.contains { other, held in
            other != key && self.number(of: other) == nil && held.port == number && held.protocol == `protocol`
        }
        if isHeld(number, protocol: `protocol`, by: key) || isHubHeld {
            throw ClientError.refusal("port_taken", ["port": "\(number)"])
        }
        write(key, LocalPortChoice(isFixed: true, port: number, protocol: `protocol`))
    }

    /// A hub is left: its entries leave the table.
    ///
    /// - Parameter bindingId: The hub.
    func forget(bindingId: String) {
        choices = choices.filter { !$0.key.hasPrefix("\(bindingId)/") }
        save()
    }

    private func isHeld(_ port: Int, protocol: String, by key: String) -> Bool {
        choices.contains { $0.key != key && $0.value.port == port && $0.value.protocol == `protocol` }
    }

    private func write(_ key: String, _ choice: LocalPortChoice) {
        choices[key] = choice
        save()
    }

    private func save() {
        defaults.set(try? JSONEncoder().encode(choices), forKey: Client.settingsKeyLocalPorts)
    }
}
