package io.github.iffix.neutrino

import java.security.cert.CertificateException

/**
 * The certificate a hub's address presented is not the one the binding pins.
 *
 * @param message What was presented.
 */
class HubUntrustedException(message: String) : CertificateException(message)
