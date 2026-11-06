"""Update the IMF PortWatch data (PortWatch itself updates weekly).

Writes to OUT_DIR:
  portwatch_ports_list.csv        all ~2,000 ports with coordinates (full CSV export, small)
  portwatch_ports_daily_SAU.csv   daily calls and trade estimates, Saudi ports only
  portwatch_chokepoints_daily.csv daily transits, all ~28 chokepoints

The two daily tables are updated incrementally. PortWatch's server cannot export or filter
the full daily table reliably (exports fail, `ISO3 = ...` and whole-year ID lists time out,
`resultOffset` paging is rejected), but it answers per-month requests. So the script starts
from the copy already in OUT_DIR (or the seed in data/seed/), re-downloads the most recent
REFETCH_MONTHS months plus anything newer, one month at a time, and merges.

A month that fails is reported and the previous copy is kept. Exit code 1 only when a
dataset has no data at all.

Usage: python refresh_portwatch.py OUT_DIR [SEED_DIR]
"""
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

PW = "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services"
PORTS_LIST = (("PortWatch_ports_database", "Ports_database", "PortWatch_Ports", "Ports"), "portwatch_ports_list.csv")
DAILY = [  # (service, output file, server-side filter to try first, local row filter)
    ("Daily_Ports_Data", "portwatch_ports_daily_SAU.csv", "ISO3 = 'SAU'", lambda d: d[d.ISO3 == "SAU"]),
    ("Daily_Chokepoints_Data", "portwatch_chokepoints_daily.csv", None, lambda d: d),
]
KEY = ["portid", "date"]
REFETCH_MONTHS = 2   # PortWatch revises recent weeks, so the last months are always re-downloaded
GAP_LOOKBACK_MONTHS = 12   # months with no rows this far back are retried (an earlier run failed them)
ID_CHUNK = 1000
TRIES = 4


def get_json(url, method="get", tries=TRIES, **kw):
    """JSON from the ArcGIS server, retrying timeouts, non-JSON pages and transient errors."""
    for attempt in range(tries):
        try:
            r = requests.request(method, url, timeout=300, **kw).json()
            if "error" not in r:
                return r
            err = r["error"]
        except (requests.RequestException, ValueError) as e:
            err = f"{e.__class__.__name__}: {e}"
        if attempt < tries - 1:
            time.sleep(15 * (attempt + 1))
    raise RuntimeError(err)


def query(layer_url, tries=TRIES, **params):
    return get_json(f"{layer_url}/query", method="post", tries=tries, data={"f": "json", **params})


def ports_list(out):
    """Small dataset: the full CSV export works."""
    services, name = PORTS_LIST
    for service in services:
        try:
            item = get_json(f"{PW}/{service}/FeatureServer/0", params={"f": "json"}).get("serviceItemId")
        except RuntimeError:
            continue
        r = requests.get(f"https://portwatch.imf.org/api/download/v1/items/{item}/csv?layers=0", timeout=300)
        if r.status_code == 200 and not r.text.lstrip().startswith(("<", "{")):
            (out / name).write_bytes(r.content)
            print(f"{name}: {len(pd.read_csv(out / name)):,} rows")
            return True
        print(f"{name}: export HTTP {r.status_code} {r.text[:120]!r}")
    return False


def month_ids(layer_url, y, m, server_filter):
    """The month's ObjectIds, and the server-side filter if it worked (None once it has failed).
    The filter is optional (rows are also filtered locally), so it gets one try."""
    base = f"year = {y} AND month = {m}"
    if server_filter:
        try:
            r = query(layer_url, tries=1, where=f"{base} AND {server_filter}", returnIdsOnly="true")
            return sorted(r.get("objectIds") or []), server_filter
        except RuntimeError as e:
            print(f"  {y}-{m:02d}: '{server_filter}' filter failed ({e}); not using it for the rest of this run")
    return sorted(query(layer_url, where=base, returnIdsOnly="true").get("objectIds") or []), None


def month_rows(layer_url, meta, ids, keep):
    """Fetch the given ObjectIds in chunks."""
    parts = []
    for i in range(0, len(ids), ID_CHUNK):
        r = query(layer_url, objectIds=",".join(map(str, ids[i:i + ID_CHUNK])), outFields="*", returnGeometry="false")
        parts.append(pd.DataFrame([f["attributes"] for f in r["features"]]))
    df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    for f in meta["fields"]:  # datetime fields arrive as milliseconds since 1970
        if f["type"] == "esriFieldTypeDate" and f["name"] in df:
            df[f["name"]] = pd.to_datetime(df[f["name"]], unit="ms")
    return keep(df) if len(df) else df


def update_daily(out, seed_dir, service, name, server_filter, keep):
    """Merge freshly downloaded recent months into the existing copy. Returns False if no data at all."""
    path = out / name
    seed = seed_dir / f"{name}.gz" if seed_dir else None
    old = pd.read_csv(path) if path.exists() else pd.read_csv(seed) if seed and seed.exists() else pd.DataFrame()
    if len(old):
        old["date"] = pd.to_datetime(old.date).dt.strftime("%Y-%m-%d")
        last = pd.Timestamp(old.date.max())
        start = (last - pd.DateOffset(months=REFETCH_MONTHS - 1)).replace(day=1)
        have = set(pd.PeriodIndex(old.date, freq="M"))
        gaps = [p for p in pd.period_range(last - pd.DateOffset(months=GAP_LOOKBACK_MONTHS), start, freq="M")
                if p not in have and p < start.to_period("M")]
        months = gaps + list(pd.period_range(start, date.today(), freq="M"))
        print(f"{name}: have {len(old):,} rows to {last:%Y-%m-%d}; refreshing from {start:%Y-%m}"
              + (f", plus missing months {', '.join(map(str, gaps))}" if gaps else ""))
    else:
        months = list(pd.period_range("2019-01", date.today(), freq="M"))
        print(f"{name}: no existing copy; downloading everything from 2019 (slow)")

    url = f"{PW}/{service}/FeatureServer/0"
    try:
        meta = get_json(url, params={"f": "json"})
    except RuntimeError as e:
        print(f"::warning::{name}: PortWatch layer unavailable ({e}); keeping the existing copy")
        return save(old, path)

    new, failed = [], []
    for p in months:
        try:
            ids, server_filter = month_ids(url, p.year, p.month, server_filter)
            rows = month_rows(url, meta, ids, keep)
            print(f"  {p}: {len(rows):,} rows")
            if len(rows):
                new.append(rows)
        except RuntimeError as e:
            print(f"  {p}: FAILED ({e})")
            failed.append(str(p))
    if failed:
        print(f"::warning::{name}: months {', '.join(failed)} could not be downloaded; previous rows kept for them")
    if new:
        fresh = pd.concat(new, ignore_index=True)
        fresh["date"] = pd.to_datetime(fresh.date).dt.strftime("%Y-%m-%d")
        old = pd.concat([old, fresh], ignore_index=True).drop_duplicates(KEY, keep="last")
    return save(old, path)


def save(df, path):
    if not len(df):
        print(f"{path.name}: no data")
        return False
    df = df.sort_values(KEY[::-1]).reset_index(drop=True)
    df.to_csv(path, index=False)
    print(f"{path.name}: {len(df):,} rows, {df.date.min()} to {df.date.max()}")
    return True


def main(out, seed_dir=None):
    out.mkdir(parents=True, exist_ok=True)
    ok = ports_list(out) or (out / PORTS_LIST[1]).exists()
    if not ok:
        print(f"::warning::{PORTS_LIST[1]}: download failed and no previous copy")
    results = [update_daily(out, seed_dir, *d) for d in DAILY]
    if not (ok and all(results)):
        sys.exit("a PortWatch dataset has no data")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "."),
         Path(sys.argv[2]) if len(sys.argv) > 2 else None)
