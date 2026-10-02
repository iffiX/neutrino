package io.github.iffix.neutrino.forward

/**
 * The job running on a forwarded entry's row.
 *
 * @property wordKey The catalog key of the in-progress word its button shows.
 */
enum class PortForwardJob(val wordKey: String) {
    /** Connect on a port entry: the loopback is being bound. */
    FORWARDING("ui.job.forwarding"),

    /** Disconnect on a port entry: the listener and its connections are being closed. */
    DISCONNECTING("ui.job.disconnecting"),

    /** Open locally on a web entry: the forward, the token, then the browser. */
    OPENING("ui.job.opening"),
}
