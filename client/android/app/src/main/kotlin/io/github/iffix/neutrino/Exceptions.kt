package io.github.iffix.neutrino

import java.io.IOException
import java.security.cert.CertificateException

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
