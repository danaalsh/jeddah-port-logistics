"""Download the latest IMF PortWatch data (updated weekly).

Writes to OUT_DIR:
  portwatch_ports_daily_SAU.csv   daily calls and trade estimates, Saudi ports only
  portwatch_chokepoints_daily.csv daily transits, all ~28 chokepoints
  portwatch_ports_list.csv        all ~2,000 ports with coordinates

The server times out on filtered queries over the full daily table (e.g. ISO3 = 'SAU'),
so each dataset is fetched as its full CSV export and filtered locally. Large exports are
generated on request, so the export is polled until ready. If it never arrives, the layer
is paged through year by year (a filter the server answers quickly).

Usage: python refresh_portwatch.py OUT_DIR
"""
import sys
import time
from datetime import date
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
EXPORT_WAIT_S = 15 * 60
POLL_S = 20


def layer_meta(layer_url):
    meta = requests.get(layer_url, params={"f": "json"}, timeout=60).json()
    return None if "error" in meta else meta


def bulk_csv(item, dest):
    """Full CSV export via the ArcGIS Hub item ID, waiting while it is generated. True on success."""
    urls = [f"https://portwatch.imf.org/api/download/v1/items/{item}/csv?layers=0",
            f"https://hub.arcgis.com/api/download/v1/items/{item}/csv?redirect=true&layers=0"]
    deadline = time.monotonic() + EXPORT_WAIT_S
    while True:
        for url in urls:
            with requests.get(url, stream=True, timeout=900) as r:
                head = r.raw.read(300, decode_content=True)
                if r.status_code == 200 and not head.lstrip().startswith((b"<", b"{")) and b"," in head:
                    with open(dest, "wb") as f:
                        f.write(head)
                        for block in r.iter_content(1 << 20):
                            f.write(block)
                    return True
                print(f"  export not ready from {url.split('/api/')[0]}: HTTP {r.status_code} "
                      f"{head[:120].decode('utf-8', 'replace')!r}")
        if time.monotonic() > deadline:
            return False
        time.sleep(POLL_S)


def query_pages(layer_url, meta, where, keep):
    """Page through `where` with resultOffset; returns the kept rows."""
    page = min(meta.get("maxRecordCount") or 1000, 2000)
    oid = meta.get("objectIdField") or "ObjectId"
    rows, offset = [], 0
    while True:
        r = requests.post(f"{layer_url}/query", timeout=300, data={
            "where": where, "outFields": "*", "returnGeometry": "false", "f": "json",
            "orderByFields": oid, "resultOffset": offset, "resultRecordCount": page}).json()
        if "error" in r:
            raise RuntimeError(f"{where}: {r['error']}")
        batch = pd.DataFrame([f["attributes"] for f in r["features"]])
        if not batch.empty:
            rows.append(keep(batch) if keep else batch)
        offset += len(r["features"])
        if not r["features"] or not r.get("exceededTransferLimit"):
            return rows


def paged(layer_url, meta, keep):
    """Year by year when the layer has a `year` field (fast server-side), else everything."""
    if not any(f["name"] == "year" for f in meta["fields"]):
        return pd.concat(query_pages(layer_url, meta, "1=1", keep), ignore_index=True)
    parts = []
    for y in range(2019, date.today().year + 1):
        parts += query_pages(layer_url, meta, f"year = {y}", keep)
        print(f"  paged {y}: {sum(len(p) for p in parts):,} rows kept so far")
    df = pd.concat(parts, ignore_index=True)
    for f in meta["fields"]:  # query results send datetimes as milliseconds since 1970
        if f["type"] == "esriFieldTypeDate" and f["name"] in df:
            df[f["name"]] = pd.to_datetime(df[f["name"]], unit="ms")
    return df


def fetch(services, keep, tmp):
    for service in services:
        url = f"{PW}/{service}/FeatureServer/0"
        meta = layer_meta(url)
        if not meta:
            continue
        print(f"{service}: item {meta.get('serviceItemId')}")
        if meta.get("serviceItemId") and bulk_csv(meta["serviceItemId"], tmp):
            df = pd.concat((keep(c) if keep else c) for c in pd.read_csv(tmp, chunksize=200_000))
            tmp.unlink()
            return df
        print(f"{service}: no CSV export, paging through the layer instead")
        return paged(url, meta, keep)
    raise RuntimeError(f"none of {services} found")


def main(out):
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "_download.csv"
    failed = []
    for services, name, keep in DATASETS:
        try:
            df = fetch(services, keep, tmp)
            df.to_csv(out / name, index=False)
            print(f"{name}: {len(df):,} rows")
        except (requests.RequestException, RuntimeError, ValueError) as e:
            print(f"{name}: FAILED ({e.__class__.__name__}: {e})")
            failed.append(name)
        tmp.unlink(missing_ok=True)
    if failed:
        sys.exit(f"failed: {', '.join(failed)}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "."))
