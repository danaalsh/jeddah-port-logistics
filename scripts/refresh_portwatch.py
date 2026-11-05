"""Download the latest IMF PortWatch data (updated weekly).

Writes to OUT_DIR:
  portwatch_ports_daily_SAU.csv   daily calls and trade estimates, Saudi ports only
  portwatch_chokepoints_daily.csv daily transits, all ~28 chokepoints
  portwatch_ports_list.csv        all ~2,000 ports with coordinates

The server times out on filtered queries over the full daily table, so each dataset is
fetched as its full CSV export (via the layer's ArcGIS Hub item ID) and filtered locally.

Usage: python refresh_portwatch.py OUT_DIR
"""
import sys
from pathlib import Path

import pandas as pd
import requests

PW = "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services"
DATASETS = [  # (service names to try, output file, row filter)
    (("PortWatch_ports_database", "Ports_database", "PortWatch_Ports", "Ports"),
     "portwatch_ports_list.csv", None),
    (("Daily_Ports_Data",), "portwatch_ports_daily_SAU.csv", lambda c: c[c.ISO3 == "SAU"]),
    (("Daily_Chokepoints_Data",), "portwatch_chokepoints_daily.csv", None),
]


def bulk_csv(layer_url, dest):
    """Download a layer's full CSV export via its ArcGIS Hub item ID. Returns True on success."""
    item = requests.get(layer_url, params={"f": "json"}, timeout=60).json().get("serviceItemId")
    if not item:
        return False
    for url in (f"https://portwatch.imf.org/api/download/v1/items/{item}/csv?layers=0",
                f"https://hub.arcgis.com/api/download/v1/items/{item}/csv?redirect=true&layers=0"):
        with requests.get(url, stream=True, timeout=900) as r:
            head = r.raw.read(200, decode_content=True)
            if r.status_code != 200 or head.lstrip().startswith(b"<") or b"," not in head:
                continue
            with open(dest, "wb") as f:
                f.write(head)
                for block in r.iter_content(1 << 20):
                    f.write(block)
        return True
    return False


def main(out):
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "_download.csv"
    failed = []
    for services, name, keep in DATASETS:
        for service in services:
            try:
                if bulk_csv(f"{PW}/{service}/FeatureServer/0", tmp):
                    df = pd.concat((keep(c) if keep else c) for c in pd.read_csv(tmp, chunksize=200_000))
                    df.to_csv(out / name, index=False)
                    print(f"{name}: {len(df):,} rows")
                    break
            except requests.RequestException as e:
                print(f"{service}: {e.__class__.__name__}")
        else:
            failed.append(name)
        tmp.unlink(missing_ok=True)
    if failed:
        sys.exit(f"failed: {', '.join(failed)}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "."))
