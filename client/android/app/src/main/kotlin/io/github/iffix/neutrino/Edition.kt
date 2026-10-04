package io.github.iffix.neutrino

import io.github.iffix.neutrino.overlay.OverlayPart

/**
 * The edition table: the one way the rest of the app reaches a left-out feature.
 *
 * A left-out feature is one the mainland edition `cn` builds without, by deleting its sources from
 * the tree: NetBird. Code outside a feature's own sources never names its types; it asks this table
 * and gets the parts of the present features alone. A feature is present when its part's class is
 * in the app; each part is loaded by its class name on the first lookup.
 *
 * [current] is where the app links to, never which features it has: `BuildConfig.EDITION`, which
 * the build reads from the root `EDITION` file.
 */
object Edition {
    private val parts: Map<String, OverlayPart?> by lazy { EDITION_FEATURE_PARTS.mapValues { load(it.value) } }

    /** `intl` or `cn`. */
    val current: String
        get() = BuildConfig.EDITION

    /** The app's source, in this edition's repository. */
    val sourceUrl: String
        get() = CLIENT_SOURCE_URLS[current] ?: CLIENT_SOURCE_URLS.getValue(EDITION_INTL)

    /** The parts of the present features, in the table's order. */
    val overlayParts: List<OverlayPart>
        get() = parts.values.filterNotNull()

    /** The cores the app carries, for the About card: the present features' first. */
    val carriedCores: List<CarriedCore>
        get() = overlayParts.map { it.carriedCore } + CLIENT_CARRIED_CORES

    /**
     * Whether a left-out feature is in this app.
     *
     * @param name `netbird`.
     * @return True when its part's class is in the app.
     * @throws IllegalArgumentException When [name] is no feature.
     */
    fun hasFeature(name: String): Boolean {
        require(name in EDITION_FEATURE_PARTS) { "no feature named $name" }
        return parts[name] != null
    }

    /**
     * The part of the present feature whose overlay objects carry one provider.
     *
     * @param provider The provider name.
     * @return The part, or null when no present feature gives it.
     */
    fun overlayPart(provider: String): OverlayPart? = overlayParts.firstOrNull { it.provider == provider }

    private fun load(className: String): OverlayPart? = try {
        Class.forName(className).getField("INSTANCE").get(null) as? OverlayPart
    } catch (_: ClassNotFoundException) {
        null
    }
}
