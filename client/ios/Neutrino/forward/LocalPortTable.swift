import Foundation

/// The one table of local ports, by entry key `<binding>/<entry>`, kept in the app's settings: each entry is
/// automatic or fixed, and no two entries hold one number. An automatic entry takes its own published port when
/// no other entry holds it and nothing listens on it, else the first free number from 20000 up, and keeps that
/// pick from then on. A kept or fixed number is looked at again each time its forward is about to listen: an
/// automatic pick another program now listens on is picked again and the new number kept, and a fixed one is
/// refused.
final class LocalPortTable {
    private let defaults: UserDefaults
    private let isFree: (Int, Bool) -> Bool
    private var choices: [String: LocalPortChoice]

    /// Read the table.
    ///
    /// - Parameters:
    ///   - defaults: Where the table is written.
    ///   - isFree: Whether nothing listens on a number now, by the number and whether the table keeps it.
    init(defaults: UserDefaults, isFree: @escaping (Int, Bool) -> Bool = ForwardSocket.isFree) {
        self.defaults = defaults
        self.isFree = isFree
        let data = defaults.data(forKey: Client.settingsKeyLocalPorts)
        choices = data.flatMap { try? JSONDecoder().decode([String: LocalPortChoice].self, from: $0) } ?? [:]
    }

    /// One entry's choice.
    ///
    /// - Parameter key: The entry's key.
    /// - Returns: The choice; automatic with no pick for an entry the table does not hold.
    func choice(of key: String) -> LocalPortChoice {
        choices[key] ?? LocalPortChoice()
    }

    /// Keep the person's choice for one entry; automatic keeps the entry's pick when it was automatic already.
    ///
    /// - Parameters:
    ///   - key: The entry's key.
    ///   - choice: Automatic, or fixed with its number.
    /// - Throws: `ClientError.refused` with `port_range` for a fixed number outside 1024 to 65535, and
    ///   `port_taken {port}` when another entry holds it.
    func configure(_ key: String, _ choice: LocalPortChoice) throws {
        if choice.isFixed {
            guard Forward.fixedPorts.contains(choice.port) else { throw ClientError.refusal("port_range") }
            if isHeld(choice.port, by: key) { throw ClientError.refusal("port_taken", ["port": "\(choice.port)"]) }
            write(key, choice)
        } else {
            let before = self.choice(of: key)
            write(key, before.isFixed ? LocalPortChoice() : before)
        }
    }

    /// The number an entry's forward is about to listen on: the kept or fixed number while nothing else listens
    /// on it, else for an automatic entry a new pick, kept from then on.
    ///
    /// - Parameters:
    ///   - key: The entry's key.
    ///   - publishedPort: The entry's own port; 0 for none.
    /// - Returns: The number.
    /// - Throws: `ClientError.refused` with `port_taken {port}` when another program listens on the entry's fixed
    ///   number, and `forward_failed {detail}` when no number is free.
    func port(for key: String, publishedPort: Int) throws -> Int {
        let choice = self.choice(of: key)
        if choice.port != 0 {
            if isFree(choice.port, true) { return choice.port }
            if choice.isFixed { throw ClientError.refusal("port_taken", ["port": "\(choice.port)"]) }
        }
        let isOwnFree =
            Forward.fixedPorts.contains(publishedPort) && publishedPort != choice.port
            && !isHeld(publishedPort, by: key) && isFree(publishedPort, false)
        var pick = isOwnFree ? publishedPort : 0
        if pick == 0 {
            pick =
                (Forward.autoFirstPort...Forward.fixedPorts.upperBound).first {
                    $0 != choice.port && !isHeld($0, by: key) && isFree($0, false)
                } ?? 0
        }
        guard pick != 0 else { throw ClientError.refusal("forward_failed", ["detail": "no local port is free"]) }
        write(key, LocalPortChoice(isFixed: false, port: pick))
        return pick
    }

    /// A hub is left: its entries leave the table.
    ///
    /// - Parameter bindingId: The hub.
    func forget(bindingId: String) {
        choices = choices.filter { !$0.key.hasPrefix("\(bindingId)/") }
        save()
    }

    private func isHeld(_ port: Int, by key: String) -> Bool {
        choices.contains { $0.key != key && $0.value.port == port }
    }

    private func write(_ key: String, _ choice: LocalPortChoice) {
        choices[key] = choice
        save()
    }

    private func save() {
        defaults.set(try? JSONEncoder().encode(choices), forKey: Client.settingsKeyLocalPorts)
    }
}
