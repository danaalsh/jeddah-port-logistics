"""Download input files from the repository's `data-latest` release (refreshed weekly)."""
from pathlib import Path

import requests

REPO = "danaalsh/jeddah-port-logistics"
RELEASE = "data-latest"


def fetch(names, dest, refresh=False, optional=()):
    """Download release assets into `dest` (skipping files already there unless `refresh`).
    Tries the public download link first, then the GitHub API (for networks that only allow the API).
    Names in `optional` that are not in the release are skipped (left out of the result)."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    assets = None
    for name in names:
        path = dest / name
        if path.exists() and not refresh:
            continue
        try:
            r = requests.get(f"https://github.com/{REPO}/releases/download/{RELEASE}/{name}", timeout=600)
            r.raise_for_status()
        except requests.RequestException:
            if assets is None:
                rel = requests.get(f"https://api.github.com/repos/{REPO}/releases/tags/{RELEASE}", timeout=60)
                rel.raise_for_status()
                assets = {a["name"]: a["id"] for a in rel.json()["assets"]}
            if name not in assets and name in optional:
                print(f"{name}: not in the release yet; skipped")
                continue
            r = requests.get(f"https://api.github.com/repos/{REPO}/releases/assets/{assets[name]}",
                             headers={"Accept": "application/octet-stream"}, timeout=600)
            r.raise_for_status()
        path.write_bytes(r.content)
        print(f"downloaded {name} ({len(r.content) / 1e6:.1f} MB)")
    return {name: dest / name for name in names if (dest / name).exists()}
