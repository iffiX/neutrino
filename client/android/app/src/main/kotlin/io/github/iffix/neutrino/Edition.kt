package io.github.iffix.neutrino

/**
 * The edition the app was built as, which chooses where it links to: `BuildConfig.EDITION`, which the
 * build reads from the root `EDITION` file. The app leaves nothing out in either edition.
 */
object Edition {
    /** `intl` or `cn`. */
    val current: String
        get() = BuildConfig.EDITION

    /** The app's source, in this edition's repository. */
    val sourceUrl: String
        get() = CLIENT_SOURCE_URLS[current] ?: CLIENT_SOURCE_URLS.getValue(EDITION_INTL)

    /** Where this edition's repository shows a file, the `{blob}` of a patch link. */
    val blobUrl: String
        get() = CLIENT_BLOB_URLS[current] ?: CLIENT_BLOB_URLS.getValue(EDITION_INTL)

    /**
     * The source of one carried core as this edition links it.
     *
     * @param core The core.
     * @return Its mirror in the mainland edition where it has one, else its own source.
     */
    fun sourceUrlOf(core: CarriedCore): String =
        core.mainlandSourceUrl.takeIf { current == EDITION_CN && it.isNotEmpty() } ?: core.sourceUrl
}
