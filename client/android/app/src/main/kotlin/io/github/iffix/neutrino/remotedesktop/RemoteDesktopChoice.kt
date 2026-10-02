package io.github.iffix.neutrino.remotedesktop

import io.github.iffix.neutrino.RDP_OPTION_CODEC
import io.github.iffix.neutrino.RDP_OPTION_QUALITY

/**
 * What the Configure dialog of one shared desktop keeps for its next Connect.
 *
 * @property codec The codec asked of the machine.
 * @property quality The picture quality asked for.
 */
data class RemoteDesktopChoice(
    val codec: RemoteDesktopCodec = RemoteDesktopCodec.AUTO,
    val quality: RemoteDesktopQuality = RemoteDesktopQuality.BALANCED,
) {
    /**
     * The core's session options this choice sets, by RustDesk's names.
     *
     * @return `codec-preference` and `image-quality` with their values.
     */
    fun options(): List<Pair<String, String>> =
        listOf(RDP_OPTION_CODEC to codec.coreName, RDP_OPTION_QUALITY to quality.coreName)
}
