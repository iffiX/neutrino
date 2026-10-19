import Foundation

/// How the tab strip follows the session lists the hubs send: a listed session with no tab gets one at the end,
/// a listed tab takes the list's values, and a tab whose session left the list of a connected hub has ended and
/// is neither kept nor shared for this phone. A hub that is not connected leaves its tabs as they are.
enum TerminalSessionMerge {
    /// The sessions the connected hubs list, in the hubs' order and each machine's order.
    ///
    /// - Parameter hubs: Every hub's view.
    /// - Returns: The listings, and the bindings whose lists they are.
    static func listed(_ hubs: [HubView]) -> (listings: [TerminalListing], listedHubs: Set<String>) {
        let connected = hubs.filter(\.isConnected)
        let listings = connected.flatMap { hub in
            hub.terminals.flatMap { machine in
                machine.sessions.map {
                    TerminalListing(
                        bindingId: hub.binding.id, deviceId: machine.deviceId, machineName: machine.name, session: $0)
                }
            }
        }
        return (listings, Set(connected.map(\.binding.id)))
    }

    /// The tabs after one round of lists.
    ///
    /// - Parameters:
    ///   - tabs: The tabs before.
    ///   - listings: The sessions the connected hubs list.
    ///   - listedHubs: The bindings whose lists `listings` are.
    ///   - dismissed: Sessions whose tab a person closed; they get no tab again.
    /// - Returns: The tabs after.
    static func merge(
        _ tabs: [TerminalTab], listings: [TerminalListing], listedHubs: Set<String>, dismissed: Set<String>
    ) -> [TerminalTab] {
        let byId = Dictionary(listings.map { ($0.session.sessionId, $0) }, uniquingKeysWith: { first, _ in first })
        let merged = tabs.map { tab -> TerminalTab in
            var next = tab
            if let listing = byId[tab.sessionId] {
                next.title = listing.session.title
                next.owner = listing.session.owner
                next.ownerName = listing.session.ownerName
                next.isOwned = listing.session.isOwned
                next.isPersistent = listing.session.isPersistent
                next.isShared = listing.session.isShared
                next.attachedCount = listing.session.attachedCount
                next.isListed = true
            } else if tab.isListed && listedHubs.contains(tab.bindingId) && tab.phase != .ended {
                next.phase = .ended
                next.attachedCount = 0
                next.isPersistent = false
                next.isShared = false
            }
            return next
        }
        let known = Set(tabs.map(\.sessionId))
        let added = listings.filter {
            !known.contains($0.session.sessionId) && !dismissed.contains($0.session.sessionId)
        }
        .map { listing in
            TerminalTab(
                sessionId: listing.session.sessionId,
                bindingId: listing.bindingId,
                deviceId: listing.deviceId,
                name: listing.machineName,
                title: listing.session.title,
                owner: listing.session.owner,
                ownerName: listing.session.ownerName,
                isOwned: listing.session.isOwned,
                isPersistent: listing.session.isPersistent,
                isShared: listing.session.isShared,
                attachedCount: listing.session.attachedCount,
                isListed: true,
                phase: .detached)
        }
        return merged + added
    }
}
