"""Build the export route planner page from the latest data (what notebook 03 does, without the notebook).

Usage: python scripts/build_planner.py OUT_DIR [--data DIR] [--cache DIR]
Writes OUT_DIR/index.html (the planner) and OUT_DIR/export_options.csv. Downloads the weekly
data-latest release files into --data (default OUT_DIR/../data) unless they are already there.
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from sim import data, exports, model, network  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--data", type=Path)
    ap.add_argument("--cache", type=Path)
    a = ap.parse_args()
    out = a.out
    data_dir = a.data or out.parent / "data"
    cache_dir = a.cache or out.parent / "cache"
    for d in (out, data_dir, cache_dir):
        d.mkdir(parents=True, exist_ok=True)

    files = data.fetch(["gcc_major.osm.pbf", "osm_date.txt", "portwatch_ports_list.csv",
                        "portwatch_chokepoints_daily.csv", "gpr_monthly.xls"], data_dir, optional=["gpr_monthly.xls"])
    cfg = exports.load_config(REPO / "config/exports")
    G = network.build_graph(files["gcc_major.osm.pbf"], cache_dir, truck_max_kph=80)
    crossings = pd.read_csv(REPO / "config/border_crossings.csv")
    network.add_border_delays(G, crossings)
    network.set_costs(G, model.load_params(REPO / "config/costs.csv"))

    dis, choke_date = exports.disruption(pd.read_csv(files["portwatch_chokepoints_daily.csv"]))
    gpr = exports.gpr_levels(files.get("gpr_monthly.xls"))
    closures = exports.conditions(dis, cfg["p"])
    print(f"closed today: {closures['today']}; straits data to {choke_date}; GPR: {'loaded' if gpr else 'not loaded'}")

    modon = pd.read_csv(REPO / "config/industrial_cities_modon.csv")
    cfg["sites"] = pd.concat([cfg["sites"], pd.DataFrame(dict(
        site_id=modon.dest_id, name=modon.name, type="industrial_city", lat=modon.lat, lon=modon.lon,
        commodities="manufactured", source=modon.source))], ignore_index=True)
    pw = pd.read_csv(files["portwatch_ports_list.csv"]).set_index("portid")[["lat", "lon"]]
    cfg["ports"] = cfg["ports"].join(pw, on="portwatch_id")

    land = exports.land_legs(G, cfg["sites"], cfg["ports"], cfg["pipelines"], crossings)
    seas = exports.sea_legs(cfg["ports"], cfg["markets"], closures)
    opts = exports.options(cfg, land, seas, dis, gpr, closures)
    print(f"{len(opts)} route options; {opts.status.value_counts().to_dict()}")

    meta = dict(choke_date=choke_date, osm_date=files["osm_date.txt"].read_text().strip())
    page = exports.page_data(cfg, land, seas, dis, gpr, closures, opts, meta,
                             json.loads((REPO / "simulator/countries.geojson").read_text()))
    size = exports.build_page(REPO / "simulator/planner_template.html", out / "index.html", page)
    opts.to_csv(out / "export_options.csv", index=False)
    print(f"wrote {out / 'index.html'} ({size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
