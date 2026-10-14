package io.github.iffix.neutrino.netbird

/** The route and search domain lists NetBird's core hands the app, as `;`-joined text. */
object NetbirdRoutes {
    /**
     * Read one list.
     *
     * @param text The core's text, such as `100.64.0.0/10;192.168.10.0/24`, or null.
     * @return Each item once, sorted, blanks dropped.
     */
    fun parse(text: String?): List<String> =
        text.orEmpty().split(';', ',').map { it.trim() }.filter { it.isNotEmpty() }.distinct().sorted()
}
