package gate

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"errors"
	"fmt"
	"math/big"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// LoadOrCreateCertificate reads the hub's DTLS certificate and its key from
// dir, making a new self-signed pair when either file is missing, and
// writes the certificate's fingerprint beside them. The directory is made
// with mode 0700 when it does not exist. It returns an error when a file
// cannot be read or written, or holds something that is not a certificate
// or its key.
func LoadOrCreateCertificate(dir string) (tls.Certificate, error) {
	if err := os.MkdirAll(dir, GateCertificateDirMode); err != nil {
		return tls.Certificate{}, fmt.Errorf("certificate directory: %w", err)
	}
	certificatePath := filepath.Join(dir, GateCertificateFile)
	keyPath := filepath.Join(dir, GateCertificateKeyFile)
	certificatePEM, errCertificate := os.ReadFile(certificatePath)
	keyPEM, errKey := os.ReadFile(keyPath)
	var certificate tls.Certificate
	switch {
	case errCertificate == nil && errKey == nil:
		pair, err := tls.X509KeyPair(certificatePEM, keyPEM)
		if err != nil {
			return tls.Certificate{}, fmt.Errorf("%s: %w", certificatePath, err)
		}
		certificate = pair
	case errors.Is(errCertificate, os.ErrNotExist) || errors.Is(errKey, os.ErrNotExist):
		pair, newCertificatePEM, newKeyPEM, err := newCertificate()
		if err != nil {
			return tls.Certificate{}, err
		}
		if err := writeFile(keyPath, newKeyPEM, GateCertificateKeyMode); err != nil {
			return tls.Certificate{}, err
		}
		if err := writeFile(certificatePath, newCertificatePEM, GateCertificateMode); err != nil {
			return tls.Certificate{}, err
		}
		certificate = pair
	case errCertificate != nil:
		return tls.Certificate{}, fmt.Errorf("%s: %w", certificatePath, errCertificate)
	default:
		return tls.Certificate{}, fmt.Errorf("%s: %w", keyPath, errKey)
	}
	fingerprintPath := filepath.Join(dir, GateFingerprintFile)
	if err := writeFile(fingerprintPath, []byte(Fingerprint(certificate)+"\n"), GateFingerprintMode); err != nil {
		return tls.Certificate{}, err
	}
	return certificate, nil
}

// Fingerprint is the SHA-256 of a certificate's DER, as a link and an SDP
// carry it: uppercase hex pairs joined by colons.
func Fingerprint(certificate tls.Certificate) string {
	if len(certificate.Certificate) == 0 {
		return ""
	}
	return FingerprintOf(certificate.Certificate[0])
}

// FingerprintOf is the fingerprint of one certificate's DER.
func FingerprintOf(der []byte) string {
	sum := sha256.Sum256(der)
	parts := make([]string, len(sum))
	for i, value := range sum {
		parts[i] = fmt.Sprintf("%02X", value)
	}
	return strings.Join(parts, ":")
}

// newCertificate makes a self-signed ECDSA P-256 certificate and returns it
// with its two PEM encodings.
func newCertificate() (tls.Certificate, []byte, []byte, error) {
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return tls.Certificate{}, nil, nil, fmt.Errorf("certificate key: %w", err)
	}
	serial, err := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), GateSerialBits))
	if err != nil {
		return tls.Certificate{}, nil, nil, fmt.Errorf("certificate serial: %w", err)
	}
	now := time.Now()
	template := &x509.Certificate{
		SerialNumber:          serial,
		Subject:               pkix.Name{CommonName: GateCertificateName},
		NotBefore:             now.Add(-GateCertificateBackdate),
		NotAfter:              now.Add(GateCertificateLifetime),
		KeyUsage:              x509.KeyUsageDigitalSignature,
		ExtKeyUsage:           []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth, x509.ExtKeyUsageClientAuth},
		BasicConstraintsValid: true,
	}
	der, err := x509.CreateCertificate(rand.Reader, template, template, &key.PublicKey, key)
	if err != nil {
		return tls.Certificate{}, nil, nil, fmt.Errorf("certificate: %w", err)
	}
	keyDER, err := x509.MarshalECPrivateKey(key)
	if err != nil {
		return tls.Certificate{}, nil, nil, fmt.Errorf("certificate key: %w", err)
	}
	certificatePEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
	keyPEM := pem.EncodeToMemory(&pem.Block{Type: "EC PRIVATE KEY", Bytes: keyDER})
	leaf, err := x509.ParseCertificate(der)
	if err != nil {
		return tls.Certificate{}, nil, nil, fmt.Errorf("certificate: %w", err)
	}
	return tls.Certificate{Certificate: [][]byte{der}, PrivateKey: key, Leaf: leaf}, certificatePEM, keyPEM, nil
}

// writeFile writes a file whole with mode, replacing it atomically.
func writeFile(path string, data []byte, mode os.FileMode) error {
	temporary := path + ".tmp"
	if err := os.WriteFile(temporary, data, mode); err != nil {
		return fmt.Errorf("write %s: %w", path, err)
	}
	if err := os.Chmod(temporary, mode); err != nil {
		return fmt.Errorf("chmod %s: %w", path, err)
	}
	if err := os.Rename(temporary, path); err != nil {
		return fmt.Errorf("rename %s: %w", path, err)
	}
	return nil
}
