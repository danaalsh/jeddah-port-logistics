"""Download the latest IMF PortWatch data (updated weekly).

Writes to OUT_DIR:
  portwatch_ports_daily_SAU.csv   daily calls and trade estimates, Saudi ports only
  portwatch_chokepoints_daily.csv daily transits, all ~28 chokepoints
  portwatch_ports_list.csv        all ~2,000 ports with coordinates

The server times out on filtered queries over the full daily table (e.g. ISO3 = 'SAU'),
so each dataset is fetched as its full CSV export and filtered locally. Large exports are
generated on request (HTTP 202 "being generated", can take well over 15 minutes), so all
exports are requested up front and then polled until ready. If one never arrives, its rows
are listed by ObjectId year by year (a filter the server answers quickly) and fetched by ID;
the layer does not support resultOffset paging.

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
EXPORT_WAIT_S = 60 * 60   # per dataset, counted from when its export was requested
POLL_S = 30
ID_CHUNK = 1000


def layer_meta(layer_url, tries=3):
    for attempt in range(tries):
        meta = requests.get(layer_url, params={"f": "json"}, timeout=60).json()
        if "error" not in meta:
            return meta
        print(f"  {layer_url.split('/services/')[1]}: {meta['error']}")
        time.sleep(10 * (attempt + 1))
    return None


def export_urls(item):
    return [f"https://portwatch.imf.org/api/download/v1/items/{item}/csv?layers=0",
            f"https://hub.arcgis.com/api/download/v1/items/{item}/csv?redirect=true&layers=0"]


def request_export(item):
    """Ask the Hub to start generating an export; the response itself is not needed."""
    try:
        requests.get(export_urls(item)[0], timeout=60).close()
    except requests.RequestException:
        pass


def bulk_csv(item, dest, deadline):
    """Full CSV export via the ArcGIS Hub item ID, waiting while it is generated. True on success."""
    last = None
    while True:
        for url in export_urls(item):
            with requests.get(url, stream=True, timeout=900) as r:
                head = r.raw.read(300, decode_content=True)
                if r.status_code == 200 and not head.lstrip().startswith((b"<", b"{")) and b"," in head:
                    with open(dest, "wb") as f:
                        f.write(head)
                        for block in r.iter_content(1 << 20):
                            f.write(block)
                    return True
                status = f"HTTP {r.status_code} {head[:110].decode('utf-8', 'replace')!r}"
                if status != last:  # log changes only, not every poll
                    print(f"  export not ready ({url.split('/api/')[0]}): {status}")
                    last = status
        if time.monotonic() > deadline:
            return False
        time.sleep(POLL_S)


def query(layer_url, **params):
    r = requests.post(f"{layer_url}/query", data={"f": "json", **params}, timeout=300).json()
    if "error" in r:
        raise RuntimeError(f"{params.get('where', 'objectIds')}: {r['error']}")
    return r


def by_ids(layer_url, meta, keep):
    """List ObjectIds year by year (or all at once if there is no `year` field), then fetch by ID."""
    years = range(2019, date.today().year + 1) if any(f["name"] == "year" for f in meta["fields"]) else [None]
    chunk = min(meta.get("maxRecordCount") or ID_CHUNK, ID_CHUNK)
    parts = []
    for y in years:
        ids = sorted(query(layer_url, where=f"year = {y}" if y else "1=1", returnIdsOnly="true").get("objectIds") or [])
        for i in range(0, len(ids), chunk):
            r = query(layer_url, objectIds=",".join(map(str, ids[i:i + chunk])), outFields="*", returnGeometry="false")
            batch = pd.DataFrame([f["attributes"] for f in r["features"]])
            if not batch.empty:
                parts.append(keep(batch) if keep else batch)
        print(f"  {y or 'all'}: {len(ids):,} rows listed, {sum(len(p) for p in parts):,} kept so far")
    df = pd.concat(parts, ignore_index=True)
    for f in meta["fields"]:  # query results send datetimes as milliseconds since 1970
        if f["type"] == "esriFieldTypeDate" and f["name"] in df:
            df[f["name"]] = pd.to_datetime(df[f["name"]], unit="ms")
    return df


def resolve(services):
    """First service name that answers, with its layer URL and metadata."""
    for service in services:
        url = f"{PW}/{service}/FeatureServer/0"
        meta = layer_meta(url)
        if meta:
            return service, url, meta
    raise RuntimeError(f"none of {services} answered")


def fetch(service, url, meta, keep, tmp, deadline):
    item = meta.get("serviceItemId")
    print(f"{service}: item {item}")
    if item and bulk_csv(item, tmp, deadline):
        df = pd.concat((keep(c) if keep else c) for c in pd.read_csv(tmp, chunksize=200_000))
        tmp.unlink()
        return df
    print(f"{service}: no CSV export in time, fetching rows by ObjectId instead")
    return by_ids(url, meta, keep)


def main(out):
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "_download.csv"
    jobs, failed = [], []
    for services, name, keep in DATASETS:  # request every export first so they generate in parallel
        try:
            service, url, meta = resolve(services)
            if meta.get("serviceItemId"):
                request_export(meta["serviceItemId"])
            jobs.append((name, keep, service, url, meta, time.monotonic() + EXPORT_WAIT_S))
        except (requests.RequestException, RuntimeError, ValueError) as e:
            print(f"{name}: FAILED ({e.__class__.__name__}: {e})")
            failed.append(name)
    for name, keep, service, url, meta, deadline in jobs:
        try:
            df = fetch(service, url, meta, keep, tmp, deadline)
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
