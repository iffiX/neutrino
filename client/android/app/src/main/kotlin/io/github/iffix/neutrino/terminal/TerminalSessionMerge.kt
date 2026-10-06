package io.github.iffix.neutrino.terminal

import io.github.iffix.neutrino.channel.ChannelTerminalSession
import io.github.iffix.neutrino.channel.HubView

/**
 * How the tab strip follows the session lists the hubs send: a listed session with no tab gets
 * one at the end, a listed tab takes the list's values, and a tab whose session left the list
 * of a connected hub has ended and is neither kept nor shared for this phone. A hub that is not
 * connected leaves its tabs as they are.
 */
object TerminalSessionMerge {
    /**
     * The sessions the connected hubs list, in the hubs' order and each machine's order.
     *
     * @param hubs Every hub's view.
     * @return The listings, and the bindings whose lists they are.
     */
    fun listed(hubs: List<HubView>): Pair<List<Listing>, Set<String>> {
        val connected = hubs.filter { it.isConnected }
        val listings = connected.flatMap { hub ->
            hub.terminals.flatMap { machine ->
                machine.sessions.map { Listing(hub.binding.id, machine.deviceId, machine.name, it) }
            }
        }
        return listings to connected.map { it.binding.id }.toSet()
    }

    /**
     * The tabs after one round of lists.
     *
     * @param tabs The tabs before.
     * @param listings The sessions the connected hubs list.
     * @param listedHubs The bindings whose lists [listings] are.
     * @param dismissed Sessions whose tab a person closed; they get no tab again.
     * @return The tabs after.
     */
    fun merge(
        tabs: List<TerminalTab>,
        listings: List<Listing>,
        listedHubs: Set<String>,
        dismissed: Set<String>,
    ): List<TerminalTab> {
        val byId = listings.associateBy { it.session.sessionId }
        val merged = tabs.map { tab ->
            val listing = byId[tab.sessionId]
            when {
                listing != null -> tab.copy(
                    title = listing.session.title,
                    owner = listing.session.owner,
                    ownerName = listing.session.ownerName,
                    isOwned = listing.session.isOwned,
                    isPersistent = listing.session.isPersistent,
                    isShared = listing.session.isShared,
                    attachedCount = listing.session.attachedCount,
                    isListed = true,
                )

                tab.isListed && tab.bindingId in listedHubs && tab.phase != TerminalPhase.ENDED ->
                    tab.copy(phase = TerminalPhase.ENDED, attachedCount = 0, isPersistent = false, isShared = false)

                else -> tab
            }
        }
        val known = tabs.map { it.sessionId }.toSet()
        val added = listings
            .filter { it.session.sessionId !in known && it.session.sessionId !in dismissed }
            .map { listing ->
                TerminalTab(
                    sessionId = listing.session.sessionId,
                    bindingId = listing.bindingId,
                    deviceId = listing.deviceId,
                    name = listing.machineName,
                    title = listing.session.title,
                    owner = listing.session.owner,
                    ownerName = listing.session.ownerName,
                    isOwned = listing.session.isOwned,
                    isPersistent = listing.session.isPersistent,
                    isShared = listing.session.isShared,
                    attachedCount = listing.session.attachedCount,
                    isListed = true,
                    phase = TerminalPhase.DETACHED,
                )
            }
        return merged + added
    }

    /**
     * One session a hub lists, with where it runs.
     *
     * @property bindingId The hub.
     * @property deviceId The machine.
     * @property machineName The machine's name.
     * @property session The session as listed.
     */
    data class Listing(
        val bindingId: String,
        val deviceId: String,
        val machineName: String,
        val session: ChannelTerminalSession,
    )
}
