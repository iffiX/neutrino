package io.github.iffix.neutrino.channel

import io.github.iffix.neutrino.overlay.OverlayJob

/**
 * The actions running on one hub; a button reads its own job from here and from nowhere else.
 *
 * @property isRefreshing Whether a refresh waits for the hub's state frame, a code or its 10 s.
 * @property overlayJob What the virtual network's button is doing.
 * @property isLeaving Whether a leave waits for the hub.
 * @property isOpeningPanel Whether Panel makes the panel's forward and opens the browser.
 */
data class HubJobs(
    val isRefreshing: Boolean = false,
    val overlayJob: OverlayJob = OverlayJob.NONE,
    val isLeaving: Boolean = false,
    val isOpeningPanel: Boolean = false,
) {
    /** Whether any job runs on the hub. */
    val isAnyRunning: Boolean
        get() = isRefreshing || isLeaving || isOpeningPanel || overlayJob != OverlayJob.NONE
}
