package io.github.iffix.neutrino.screen

import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import io.github.iffix.neutrino.channel.ChannelServiceEntry
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.design.DotTone
import io.github.iffix.neutrino.design.FeatureRow
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.design.PlaceholderFrame
import io.github.iffix.neutrino.design.ScreenColumn
import io.github.iffix.neutrino.design.SurfaceCard

/**
 * A service screen's body: every connected hub's entries of one type in one card, a greyed row
 * for each hub that is reconnecting, and the empty states before a hub is joined or when none
 * publishes the type.
 *
 * @param hubs Every hub joined.
 * @param type The service type.
 * @param emptyKey The catalog key of the line for no entry.
 * @param onJoin What pressing Join a hub does.
 * @param row One entry's row, given its hub, the entry, and whether a divider follows it.
 */
@Composable
fun ServiceList(
    hubs: List<HubView>,
    type: String,
    emptyKey: String,
    onJoin: () -> Unit,
    row: @Composable (HubView, ChannelServiceEntry, Boolean) -> Unit,
) {
    val words = NeutrinoTheme.words
    ScreenColumn {
        if (hubs.isEmpty()) {
            ServicesWaitFrame(onJoin)
            return@ScreenColumn
        }
        val entries = hubs.filter { it.isConnected }.flatMap { hub -> hub.servicesOf(type).map { hub to it } }
        val down = hubs.filterNot { it.isConnected }
        if (entries.isEmpty()) PlaceholderFrame(line = words.word(emptyKey))
        if (entries.isEmpty() && down.isEmpty()) return@ScreenColumn
        SurfaceCard {
            entries.forEachIndexed { index, (hub, entry) ->
                row(hub, entry, index < entries.lastIndex || down.isNotEmpty())
            }
            down.forEachIndexed { index, hub ->
                FeatureRow(marker = DotTone.OFF, isGreyed = true, hasDivider = index < down.lastIndex) {
                    BasicText(hub.binding.title, style = NeutrinoTheme.rowTitle)
                    BasicText(words.word("ui.reconnecting"), style = NeutrinoTheme.note)
                }
            }
        }
    }
}

/**
 * Who provides an entry, as the desktop client words it: the hub, then the machine.
 *
 * @param hub The hub that publishes it.
 * @param entry The entry.
 * @param fallbackHost The address to name when the hub names no machine.
 * @return The line.
 */
@Composable
fun providedBy(hub: HubView, entry: ChannelServiceEntry, fallbackHost: String): String = NeutrinoTheme.words.word(
    "ui.machine_provided_by",
    mapOf("hub" to hub.binding.title, "device" to entry.deviceName.ifEmpty { fallbackHost }),
)
