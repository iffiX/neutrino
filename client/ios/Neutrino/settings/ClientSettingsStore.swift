import Foundation

/// Where the language and the theme are kept: the app's own defaults.
final class ClientSettingsStore {
    private let defaults: UserDefaults

    /// Keep the settings in one defaults domain.
    ///
    /// - Parameter defaults: The domain.
    init(defaults: UserDefaults) {
        self.defaults = defaults
    }

    /// The settings as kept; the phone's language when it is one of the client's, and the system's palette.
    var settings: ClientSettings {
        let language = defaults.string(forKey: Client.settingsKeyLanguage).flatMap {
            Client.languages.contains($0) ? $0 : nil
        }
        let theme = defaults.string(forKey: Client.settingsKeyTheme).flatMap { Client.themes.contains($0) ? $0 : nil }
        return ClientSettings(language: language ?? Self.phoneLanguage(), theme: theme ?? Client.defaultTheme)
    }

    /// Keep new settings.
    ///
    /// - Parameter settings: The settings.
    func save(_ settings: ClientSettings) {
        defaults.set(settings.language, forKey: Client.settingsKeyLanguage)
        defaults.set(settings.theme, forKey: Client.settingsKeyTheme)
    }

    private static func phoneLanguage() -> String {
        let first = Locale.preferredLanguages.first ?? ""
        return first.hasPrefix("zh") ? "zh-CN" : Client.defaultLanguage
    }
}
