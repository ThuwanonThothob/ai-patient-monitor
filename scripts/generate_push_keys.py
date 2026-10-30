"""Create local VAPID key once. Never print the secret or replace existing keys."""
import os
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def main():
    path = Path(__file__).resolve().parents[1] / 'backend' / 'runtime' / 'webpush-private.pem'
    path.parent.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SystemExit('Existing key preserved. Do not rotate it while devices are subscribed.')
    with os.fdopen(fd, 'wb') as handle:
        handle.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    print(f'Private key saved (not displayed): {path}')
    print('Set WARD_VAPID_PRIVATE_KEY_FILE to this path. Keep it private and out of Git.')


if __name__ == '__main__':
    main()
