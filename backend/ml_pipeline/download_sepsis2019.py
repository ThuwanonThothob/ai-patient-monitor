"""Reproducible public PhysioNet subset, without credentials or third-party mirrors.

The old ZIP links no longer work. Sample filenames BEFORE inspecting outcomes;
use --per-site 0 for all 40,336 public records. Hashes are locally recorded, not
publisher-authenticated checksums. Existing completed downloads are verified.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import re
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/raw/sepsis2019"
BASE = "https://physionet.org/files/challenge-2019/1.0.0/"
SOURCE = "https://physionet.org/content/challenge-2019/1.0.0/"


def atomic_bytes(path, content):
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_bytes(content)
    os.replace(temporary, path)


def download(per_site=2000, workers=6, seed=2019):
    if per_site < 0 or not 1 <= workers <= 8:
        raise ValueError("per-site must be >= 0; workers must be 1..8")
    DATA.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=90, follow_redirects=True) as client:
        def fetch(relative):
            for attempt in range(3):
                try:
                    response = client.get(BASE + relative)
                    response.raise_for_status()
                    return response.content
                except httpx.HTTPError:
                    if attempt == 2:
                        raise
                    time.sleep(attempt + 1)

        # Retain the publisher's actual license, alongside its current page URL.
        atomic_bytes(DATA / "LICENSE.txt", fetch("LICENSE.txt"))
        selected, counts = [], {}
        for site, count in (("A", 20336), ("B", 20000)):
            folder = f"training/training_set{site}/"
            listing = fetch(folder).decode()
            names = sorted(set(re.findall(r'href="(p\d{6}\.psv)"', listing)))
            if len(names) != count:
                raise ValueError(f"Unexpected publisher listing for site {site}: {len(names)}")
            counts[site] = len(names)
            names.sort(key=lambda name: hashlib.sha256(f"{seed}:{site}:{name}".encode()).hexdigest())
            selected.extend((site, name, folder + name) for name in names[:per_site or len(names)])
            (DATA / site).mkdir(exist_ok=True)

        old = {}
        if (DATA / "manifest.json").exists():
            old = json.loads((DATA / "manifest.json").read_text()).get("files", {})

        def get(item):
            site, name, relative = item
            key = f"{site}/{name}"
            path = DATA / key
            content = path.read_bytes() if path.exists() else fetch(relative)
            digest = hashlib.sha256(content).hexdigest()
            if key in old and digest != old[key]["sha256"]:
                raise ValueError(f"Local dataset changed: {key}; refusing to silently reuse it")
            if not content.startswith(b"HR|O2Sat|Temp|") or b"|SepsisLabel" not in content.splitlines()[0]:
                raise ValueError(f"Invalid PSV response: {key}")
            if not path.exists():
                atomic_bytes(path, content)
            return key, {"sha256": digest, "url": BASE + relative, "bytes": len(content)}

        files = {}
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for future in as_completed([executor.submit(get, item) for item in selected]):
                key, info = future.result()
                files[key] = info
                if len(files) % 100 == 0:
                    print(f"Downloaded/verified {len(files)}/{len(selected)} records", flush=True)
        manifest = {"dataset": "PhysioNet Challenge 2019", "version": "1.0.0", "source": SOURCE,
                    "license_note": "See retained publisher LICENSE.txt and source page; retain attribution.",
                    "integrity": "HTTPS download + locally recorded SHA256 (not publisher verification)",
                    "sampling": "Hash-ranked filenames before reading outcomes", "seed": seed,
                    "per_site_requested": per_site, "publisher_counts": counts, "files": dict(sorted(files.items()))}
        atomic_bytes(DATA / "manifest.json", json.dumps(manifest, indent=2).encode())
    print(f"Ready: {len(files)} real records. Manifest: {DATA / 'manifest.json'}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-site", type=int, default=2000)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    download(args.per_site, args.workers)
