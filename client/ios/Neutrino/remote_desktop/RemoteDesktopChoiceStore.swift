import Foundation

/// Each shared desktop's codec and quality, by entry key `<binding>/<entry>`, kept in the app's settings as the
/// core's names.
final class RemoteDesktopChoiceStore {
    private static let fieldCodec = "codec"
    private static let fieldQuality = "quality"

    private let defaults: UserDefaults
    private var current: [String: [String: String]]

    /// Read the kept choices.
    ///
    /// - Parameter defaults: Where the choices are written.
    init(defaults: UserDefaults) {
        self.defaults = defaults
        let data = defaults.data(forKey: Client.settingsKeyDesktopChoices)
        current = data.flatMap { try? JSONDecoder().decode([String: [String: String]].self, from: $0) } ?? [:]
    }

    /// One entry's choice.
    ///
    /// - Parameter key: The entry's key.
    /// - Returns: The kept choice, or Auto and Balanced for an entry never configured.
    func choice(of key: String) -> RemoteDesktopChoice {
        guard let kept = current[key] else { return RemoteDesktopChoice() }
        return RemoteDesktopChoice(
            codec: .of(kept[Self.fieldCodec] ?? ""), quality: .of(kept[Self.fieldQuality] ?? ""))
    }

    /// Keep one entry's choice.
    ///
    /// - Parameters:
    ///   - key: The entry's key.
    ///   - choice: The choice.
    func keep(_ key: String, _ choice: RemoteDesktopChoice) {
        var next = current
        next[key] = [Self.fieldCodec: choice.codec.coreName, Self.fieldQuality: choice.quality.coreName]
        write(next)
    }

    /// A hub is left: its entries' choices go.
    ///
    /// - Parameter bindingId: The hub.
    func forget(bindingId: String) {
        write(current.filter { !$0.key.hasPrefix("\(bindingId)/") })
    }

    private func write(_ choices: [String: [String: String]]) {
        current = choices
        if let data = try? JSONEncoder().encode(choices) {
            defaults.set(data, forKey: Client.settingsKeyDesktopChoices)
        }
    }
}
