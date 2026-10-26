package io.github.iffix.neutrino

import java.io.IOException
import kotlinx.serialization.json.JsonObject

/**
 * This build carries no transport library: the class it is bound to is not in the app.
 *
 * @param className The class that was looked for.
 */
class TransportMissingException(className: String) : IllegalStateException("no transport library: $className")

/**
 * A share's server did not answer in time, or could not be reached at all.
 *
 * @param message What failed.
 * @param cause What the SMB library threw.
 */
class ShareUnreachableException(message: String, cause: Throwable? = null) : IOException(message, cause)

/**
 * A share's server answered and refused: the login, the access, or the name.
 *
 * @property code `share_login_rejected`, `share_hub_login_rejected`, `share_access_denied` or
 *   `share_not_found`.
 * @param message What was refused.
 */
class ShareRefusedException(val code: String, message: String) : IOException(message)

/**
 * A `connect` stream ended with the hub's refusal, or could not be opened, where only a socket's
 * [IOException] can say so.
 *
 * @property code The refusal's code, such as `permission_denied` or `connect_failed`.
 * @property params The refusal's parameters.
 */
class ConnectRefusedException(val code: String, val params: JsonObject) :
    IOException("the hub refused the connection: $code")

/**
 * Another program listens on the fixed local port a forward is to listen on.
 *
 * @property port The fixed number.
 */
class LocalPortTakenException(val port: Int) : IOException("local port $port is already in use")
