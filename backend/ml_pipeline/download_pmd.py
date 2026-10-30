"""Download the predeclared 3-standard-posture Experiment I subset, not all PMD."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
from ml_pipeline.download_bidmc import secure_open

DATA = Path(__file__).resolve().parents[1] / 'data/raw/pmd'
BASE = 'https://physionet.org/files/pmd/1.0.0/'


def download():
    DATA.mkdir(parents=True, exist_ok=True)
    with secure_open(BASE + 'SHA256SUMS.txt') as response:
        checksum_content = response.read()
    checksums = {line.split()[1]: line.split()[0] for line in checksum_content.decode().splitlines() if line.strip()}
    files = [f'experiment-i/S{subject}/{posture}.txt' for subject in range(1, 14) for posture in (1, 2, 3)]
    files += ['experiment-info.docx', 'experiment-i/subject-info-i.csv']
    if any(name not in checksums for name in files):
        raise ValueError('Publisher manifest does not contain the declared subset')

    def get(name):
        target = DATA / name
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == checksums[name]:
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        with secure_open(BASE + name, timeout=120) as response:
            content = response.read()
        if hashlib.sha256(content).hexdigest() != checksums[name]:
            raise ValueError('Publisher checksum mismatch: ' + name)
        temporary = target.with_suffix(target.suffix + '.part')
        temporary.write_bytes(content)
        os.replace(temporary, target)
        print('Verified ' + name, flush=True)

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(get, files))
    (DATA / 'SHA256SUMS.txt').write_bytes(checksum_content)
    manifest = {'dataset': 'A Pressure Map Dataset for In-bed Posture Classification v1.0.0',
                'source': 'https://physionet.org/content/pmd/1.0.0/',
                'license': 'Open Data Commons Attribution License v1.0',
                'citation': 'Pouyan et al. 2017. DOI: 10.1109/BHI.2017.7897206',
                'subset': 'Experiment I; all 13 subjects; positions 1, 2, 3 only',
                'labels': {'1': 'supine', '2': 'right', '3': 'left'},
                'label_source': 'experiment-info.docx, Experiment 1 Data properties (page 2)',
                'sha256': {name: checksums[name] for name in files}}
    temporary = DATA / 'manifest.json.part'
    temporary.write_text(json.dumps(manifest, indent=2))
    os.replace(temporary, DATA / 'manifest.json')
    print('PMD subset complete: 39 recordings; raw data kept local.', flush=True)


if __name__ == '__main__':
    download()
