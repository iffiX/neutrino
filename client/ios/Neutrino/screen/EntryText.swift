import Foundation

/// What an entry's row says: its dot and its provider line, as the desktop client words them.
enum EntryText {
    /// The module titles an origin code stands for, as the hub's panel titles its modules.
    static let modules = [
        "gitea_module": "Gitea",
        "vscode_module": "VS Code",
        "code_server_module": "code-server",
        "cloudcli_module": "CloudCLI",
        "codeg_module": "Codeg",
    ]

    /// The catalog keys of the module titles the panel translates, by origin code.
    static let moduleKeys = [
        "ai_gateway": "ui.module_ai_gateway",
        "samba_module": "ui.module_title.samba",
        "siyuan_module": "ui.module_title.siyuan",
        "device_share": "ui.module_title.remote_desktop",
    ]

    /// The dot of an entry's row: pulsing while its hub refreshes or its own job runs, else green when healthy
    /// and amber when not.
    ///
    /// - Parameters:
    ///   - hub: The hub that publishes it.
    ///   - entry: The entry.
    ///   - isBusy: Whether the entry's own job runs.
    /// - Returns: The tone.
    static func tone(_ hub: HubView, _ entry: ChannelServiceEntry, isBusy: Bool) -> DotTone {
        if isBusy || hub.jobs.isRefreshing { return .pulse }
        return entry.isUnhealthy ? .wait : .ok
    }

    /// Who provides an entry: `<hub>:<machine>:<module>`, the machine being the address the entry points at when
    /// the hub names none.
    ///
    /// - Parameters:
    ///   - hub: The hub that publishes it.
    ///   - entry: The entry.
    ///   - fallbackHost: The address to name when the hub names no machine.
    ///   - words: The catalog.
    /// - Returns: The line.
    static func provider(_ hub: HubView, _ entry: ChannelServiceEntry, fallbackHost: String, words: WordCatalog)
        -> String
    {
        words.word(
            "ui.provided_by",
            [
                "hub": hub.binding.title,
                "device": entry.deviceName.isEmpty ? fallbackHost : entry.deviceName,
                "module": module(entry, words: words),
            ])
    }

    private static func module(_ entry: ChannelServiceEntry, words: WordCatalog) -> String {
        if let key = moduleKeys[entry.descriptionCode] { return words.word(key) }
        if entry.descriptionCode == "container" {
            let image = entry.descriptionParams.text("image")
            let name = image.split(separator: "/").last.map(String.init) ?? ""
            return name.isEmpty ? entry.title : name
        }
        return modules[entry.descriptionCode] ?? entry.title
    }
}
