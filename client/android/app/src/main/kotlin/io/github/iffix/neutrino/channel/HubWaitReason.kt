package io.github.iffix.neutrino.channel

/** What a waiting hub row waits for, each worded as `ui.state.<name>`. */
enum class HubWaitReason {
    /** Every address of the round failed, and this phone is on none of the hub's virtual networks. */
    HUB_SILENT,

    /** Every address of the round failed while this phone is on the hub's virtual network. */
    HUB_OFF_OVERLAY,

    /** The phone has no network at all; the next round waits for its connectivity to change. */
    NO_NETWORK,

    /** An address answered with another certificate. */
    UNTRUSTED,

    /** The hub paused new devices; the join runs again after the seconds it named. */
    ADMISSION_PAUSED,

    /** The hub does not know this binding; nothing runs, and Leave is the one action. */
    UNKNOWN_DEVICE,

    /** The hub speaks another protocol number; nothing runs until a refresh. */
    TOO_OLD,

    /** The hub refused the binding's ticket; nothing runs, and Leave is the one action. */
    JOIN_REFUSED,

    /** Another socket for the same binding took over; nothing runs until a person reconnects. */
    REPLACED,

    /** The hub switched this client off; the socket stays open. */
    DISABLED,
    ;

    /** The name the catalog's `ui.state.<name>` keys and the other clients use. */
    val wireName: String
        get() = name.lowercase()
}
