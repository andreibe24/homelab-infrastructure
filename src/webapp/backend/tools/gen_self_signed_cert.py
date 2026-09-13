"""Generate a throw-away self-signed TLS certificate.

QUIC/HTTP-3 cannot start without TLS 1.3 credentials. In the cluster the certificate
comes from the cert-manager `Certificate` mounted at /etc/webapp/tls; this helper only
exists so the image stays runnable locally (`docker run`) or in a cluster where
cert-manager has not issued the Secret yet.

Uses `cryptography`, which is already a dependency of aioquic -- no openssl CLI and no
extra apt packages are needed in the runtime image.
"""
from __future__ import annotations

import datetime as dt
import ipaddress
import os
import sys

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def generate(certfile: str, keyfile: str, hostnames: list[str]) -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostnames[0])])
    alt_names: list[x509.GeneralName] = [x509.DNSName(name) for name in hostnames]
    alt_names.append(x509.IPAddress(ipaddress.ip_address("127.0.0.1")))
    now = dt.datetime.now(dt.timezone.utc)

    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=30))
        .add_extension(x509.SubjectAlternativeName(alt_names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    directory = os.path.dirname(certfile)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(certfile, "wb") as handle:
        handle.write(certificate.public_bytes(serialization.Encoding.PEM))
    with open(keyfile, "wb") as handle:
        handle.write(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
    os.chmod(keyfile, 0o600)


if __name__ == "__main__":
    cert_path = sys.argv[1]
    key_path = sys.argv[2]
    names = sys.argv[3:] or ["localhost"]
    generate(cert_path, key_path, names)
    print(f"generated self-signed certificate for {', '.join(names)} at {cert_path}")
