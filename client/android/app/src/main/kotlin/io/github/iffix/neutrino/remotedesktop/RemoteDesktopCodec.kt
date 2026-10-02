package io.github.iffix.neutrino.remotedesktop

import io.github.iffix.neutrino.RDP_MEDIACODEC_ABIS

/**
 * The codec a remote desktop session asks the machine to send, as RustDesk's
 * `codec-preference` names it.
 *
 * @property coreName The option's value in the core.
 * @property title What the picker shows; empty for [AUTO], which the catalog words.
 */
enum class RemoteDesktopCodec(val coreName: String, val title: String) {
    /** The machine and the core agree on one. */
    AUTO("auto", ""),

    /** libvpx's VP8. */
    VP8("vp8", "VP8"),

    /** libvpx's VP9. */
    VP9("vp9", "VP9"),

    /** libaom's AV1. */
    AV1("av1", "AV1"),

    /** H.264 through the device's MediaCodec decoder, in a core built with `mediacodec`. */
    H264("h264", "H264"),

    /** H.265 through the device's MediaCodec decoder, in a core built with `mediacodec`. */
    H265("h265", "H265"),
    ;

    companion object {
        /**
         * The codecs the app's core decodes on one machine, Auto first.
         *
         * @param abi The machine, as Android names it, such as `arm64-v8a`.
         * @return Auto, VP8, VP9 and AV1, then H264 and H265 where the core is built with MediaCodec.
         */
        fun offered(abi: String): List<RemoteDesktopCodec> =
            if (abi in RDP_MEDIACODEC_ABIS) entries else listOf(AUTO, VP8, VP9, AV1)

        /**
         * A codec by its core name.
         *
         * @param coreName The name kept in the settings.
         * @return The codec, or [AUTO] for a name the app does not know.
         */
        fun of(coreName: String): RemoteDesktopCodec = entries.firstOrNull { it.coreName == coreName } ?: AUTO
    }
}
