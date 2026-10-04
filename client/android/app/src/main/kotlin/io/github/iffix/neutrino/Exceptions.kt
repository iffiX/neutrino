package io.github.iffix.neutrino

import java.io.IOException
import java.security.cert.CertificateException
import kotlinx.serialization.json.JsonObject

/**
 * The certificate a hub's address presented is not the one the binding pins.
 *
 * @param message What was presented.
 */
class HubUntrustedException(message: String) : CertificateException(message)

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
 * @property code `share_login_rejected`, `share_access_denied` or `share_not_found`.
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
