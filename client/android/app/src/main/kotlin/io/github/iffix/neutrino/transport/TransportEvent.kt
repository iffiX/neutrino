package io.github.iffix.neutrino.transport

import io.github.iffix.neutrino.channel.ChannelResult
import kotlinx.serialization.json.JsonObject

/** What the transport says about one hub, in the order it says it. */
sealed interface TransportEvent {
    /**
     * A round's winner completed its handshake and opened its control stream; `hello` goes next.
     *
     * @property address The address that won.
     * @property path The way it reaches the hub, as the candidate named it.
     * @property handshakeMs How long its handshake took.
     */
    data class SessionOpen(val address: String, val path: String, val handshakeMs: Long) : TransportEvent

    /**
     * A round ended with no session.
     *
     * @property refusal The code the round ended in, null when it carried none.
     * @property nextRoundS The seconds until the transport's next round, 0 when none follows.
     */
    data class RoundEnd(val refusal: ChannelResult.Refused?, val nextRoundS: Long) : TransportEvent

    /**
     * The session ended.
     *
     * @property refusal The refusal that ended it, null when the connection dropped.
     */
    data class SessionEnd(val refusal: ChannelResult.Refused?) : TransportEvent

    /**
     * One frame from the hub.
     *
     * @property frame The frame, with its `type`.
     */
    data class Frame(val frame: JsonObject) : TransportEvent

    /** The local channel was opened again after it dropped: every hub is dialled again. */
    data object Restarted : TransportEvent
}
