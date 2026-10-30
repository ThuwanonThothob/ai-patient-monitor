"""Download only free BIDMC numerics, verifying publisher SHA256 for every file."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import urlopen
import hashlib
import json
import os
import ssl
import certifi

def secure_open(url, timeout=60):
    return urlopen(url, timeout=timeout, context=ssl.create_default_context(cafile=certifi.where()))

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/raw/bidmc'
BASE = 'https://physionet.org/files/bidmc/1.0.0/'


def download():
    DATA.mkdir(parents=True, exist_ok=True)
    with secure_open(BASE + 'SHA256SUMS.txt') as response:
        manifest = response.read().decode()
    checksums = dict((line.split()[1], line.split()[0]) for line in manifest.splitlines() if line.strip())
    files = sorted(name for name in checksums if name.endswith('_Numerics.csv'))
    if len(files) != 53:
        raise ValueError('Expected 53 BIDMC numeric recordings')

    def get(name):
        target = DATA / Path(name).name
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == checksums[name]:
            return
        with secure_open(BASE + name) as response:
            content = response.read()
        if hashlib.sha256(content).hexdigest() != checksums[name]:
            raise ValueError('Checksum mismatch: ' + name)
        temporary = target.with_suffix('.part')
        temporary.write_bytes(content)
        os.replace(temporary, target)

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(get, files))
    with secure_open(BASE + 'LICENSE') as response:
        (DATA / 'LICENSE').write_bytes(response.read())
    (DATA / 'manifest.json').write_text(json.dumps({
        'dataset': 'BIDMC PPG and Respiration Dataset', 'version': '1.0.0',
        'url': 'https://physionet.org/content/bidmc/1.0.0/',
        'license': 'Open Data Commons Attribution License v1.0',
        'sha256': {Path(name).name: checksums[name] for name in files},
    }, indent=2))
    print('Verified 53 BIDMC numeric recordings (publisher SHA256).', flush=True)


if __name__ == '__main__':
    download()
