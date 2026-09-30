package io.github.iffix.neutrino.channel

import android.annotation.SuppressLint
import io.github.iffix.neutrino.HubUntrustedException
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import javax.net.ssl.X509TrustManager

/**
 * Trusts one certificate: the one whose DER encoding has the pinned SHA-256. Chain and name are
 * not checked; the fingerprint is the hub's whole identity.
 *
 * @param fingerprint The pinned SHA-256, lower-case hex.
 */
@SuppressLint("CustomX509TrustManager")
class FingerprintTrustManager(private val fingerprint: String) : X509TrustManager {
    override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {
        val presented = chain?.firstOrNull() ?: throw HubUntrustedException("the hub presented no certificate")
        val digest = fingerprintOf(presented.encoded)
        if (fingerprint.isEmpty() || digest != fingerprint) {
            throw HubUntrustedException("the hub presented $digest, not the pinned certificate")
        }
    }

    override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?): Unit =
        throw CertificateException("this phone authenticates no client")

    override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()

    companion object {
        /**
         * The fingerprint of one certificate.
         *
         * @param der Its DER encoding.
         * @return The SHA-256, lower-case hex.
         */
        fun fingerprintOf(der: ByteArray): String =
            MessageDigest.getInstance("SHA-256").digest(der).joinToString("") { "%02x".format(it) }
    }
}
