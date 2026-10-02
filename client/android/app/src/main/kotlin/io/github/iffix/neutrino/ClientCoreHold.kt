package io.github.iffix.neutrino

import io.github.iffix.neutrino.binding.HubBinding
import io.github.iffix.neutrino.channel.HubView
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map

/** When the app core's foreground service runs, and what its notification counts. */
object ClientCoreHold {
    /**
     * Whether the service runs, each time that changes: from the first binding to the last leave.
     *
     * @param bindings Every binding, as the store keeps them.
     * @return True while any hub is bound, false once none is.
     */
    fun changes(bindings: Flow<List<HubBinding>>): Flow<Boolean> =
        bindings.map { it.isNotEmpty() }.distinctUntilChanged()

    /**
     * The hubs the notification says this phone is connected to.
     *
     * @param hubs Every hub's view.
     * @return How many have an open channel.
     */
    fun connectedCount(hubs: List<HubView>): Int = hubs.count { it.isConnected || it.isDisabled }
}
