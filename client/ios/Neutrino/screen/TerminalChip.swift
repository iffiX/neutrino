import Foundation

/// One machine of the Terminals page's chips, with the hub that manages it.
struct TerminalChip: Identifiable {
    /// The hub.
    let hub: HubView

    /// The machine.
    let machine: ChannelTerminal

    /// The machine by its hub and its id.
    var ref: TerminalMachine { TerminalMachine(bindingId: hub.binding.id, deviceId: machine.deviceId) }

    /// `<binding>/<device>`.
    var id: String { "\(hub.binding.id)/\(machine.deviceId)" }
}
