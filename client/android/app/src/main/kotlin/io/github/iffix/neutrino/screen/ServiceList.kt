package io.github.iffix.neutrino.screen

import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import io.github.iffix.neutrino.channel.ChannelServiceEntry
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.design.DotTone
import io.github.iffix.neutrino.design.FeatureRow
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.design.ScreenList
import io.github.iffix.neutrino.design.cardRows
import io.github.iffix.neutrino.design.gap

/**
 * A service screen's body: every connected hub's entries of one type in one card, a row for
 * each hub that is not connected, and one sentence when there is nothing to show.
 *
 * @param hubs Every hub joined.
 * @param type The service type.
 * @param emptyKey The catalog key of the sentence for no entry.
 * @param row One entry's row, given its hub, the entry, and whether a divider follows it.
 */
@Composable
fun ServiceList(
    hubs: List<HubView>,
    type: String,
    emptyKey: String,
    row: @Composable ColumnScope.(HubView, ChannelServiceEntry, Boolean) -> Unit,
) {
    val words = NeutrinoTheme.words
    val entries = hubs.flatMap { hub -> hub.servicesOf(type).map { hub to it } }
    val down = hubs.filterNot { it.isConnected }
    ScreenList {
        when {
            hubs.isEmpty() -> sentence(words.word("ui.services_wait_join"))

            entries.isEmpty() -> sentence(words.word(emptyKey))

            else -> cardRows(entries, key = { (hub, entry) ->
                "${hub.binding.id}/${entry.id}"
            }) { (hub, entry), divider ->
                row(hub, entry, divider)
            }
        }
        if (down.isNotEmpty()) {
            gap()
            cardRows(down, key = { "down-${it.binding.id}" }) { hub, hasDivider ->
                FeatureRow(marker = hubTone(hub), isGreyed = true, hasDivider = hasDivider) {
                    BasicText(hub.binding.title, style = NeutrinoTheme.rowTitle)
                    BasicText(hubStateWord(hub, words), style = NeutrinoTheme.note)
                }
            }
        }
    }
}

/**
 * The dot of an entry's row: pulsing while its hub refreshes or its own job runs, else green
 * when healthy and amber when not.
 *
 * @param hub The hub that publishes it.
 * @param entry The entry.
 * @param isBusy Whether the entry's own job runs.
 * @return The tone.
 */
fun entryTone(hub: HubView, entry: ChannelServiceEntry, isBusy: Boolean = false): DotTone = when {
    isBusy || hub.jobs.isRefreshing -> DotTone.PULSE
    entry.isHealthy == false -> DotTone.WAIT
    else -> DotTone.OK
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

private fun androidx.compose.foundation.lazy.LazyListScope.sentence(text: String) {
    cardRows(listOf(text), key = { "sentence" }) { line, _ ->
        FeatureRow(hasDivider = false) { BasicText(line, style = NeutrinoTheme.body) }
    }
}
