package io.github.iffix.neutrino.forward

/**
 * The job running on an app's row, or on a hub's Panel.
 *
 * @property wordKey The catalog key of the in-progress word its button shows.
 */
enum class PortForwardJob(val wordKey: String) {
    /** Stop on an app: every forward of the app is being closed. */
    DISCONNECTING("ui.job.disconnecting"),

    /** Use on an app, or Panel on a hub row: the forwards, the token where one is needed, then the browser. */
    OPENING("ui.job.opening"),
}
