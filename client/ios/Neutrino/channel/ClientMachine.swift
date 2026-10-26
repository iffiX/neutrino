import Foundation

/// What this phone says about itself in a join and in every report.
struct ClientMachine: Equatable {
    /// This installation's id.
    let machineId: String

    /// The name the phone goes by: the device name iOS gives the app.
    let hostname: String

    /// The architecture, `arm64` on an iPhone.
    let arch: String

    /// The iOS release, such as `16.7`.
    let osVersion: String

    /// The app's version.
    let version: String

    /// `neutrino_client/<version>`.
    var software: String { Client.softwarePrefix + version }

    /// The platform a client names: `{os, family, arch}`, family empty off Linux.
    var platform: [String: JSONValue] {
        ["os": .string(Client.platformOs), "family": .string(""), "arch": .string(arch)]
    }
}
