"""Scenario runs: for each origin region and destination, the cheapest port and its full route.

Route = sea leg (origin -> port) + port (handling, dwell) + road leg (port -> destination).
All costs per TEU. The cheapest option minimises generalised cost: money plus the value of
cargo time (inventory holding), so a slower route must also be cheaper in money to win.
"""
from pathlib import Path

import geopandas as gpd
import pandas as pd

from . import network, sea

SCENARIOS = {  # name -> searoute passages closed
    "baseline": [],
    "hormuz_closed": ["ormuz"],
    "babelmandeb_closed": ["babalmandab"],
    "both_closed": ["ormuz", "babalmandab"],
}


def load_params(costs_csv):
    c = pd.read_csv(costs_csv)
    return dict(zip(c.parameter, c.value.astype(float)))


def load_ports(ports_csv, portwatch_ports_csv):
    """Config ports with coordinates from the PortWatch port list."""
    ports = pd.read_csv(ports_csv)
    pw = pd.read_csv(portwatch_ports_csv).set_index("portid")[["lat", "lon"]]
    return ports.join(pw, on="portwatch_id")


def snap(G, df):
    xs, ys = network.to_work(df.lon, df.lat)
    return network.snap_points(G, xs, ys)


def road_legs(G, ports, dests):
    """Road leg from every port to every destination: {(port_key, dest_id): result or None}."""
    port_snaps = snap(G, ports)
    dest_snaps = dict(zip(dests.dest_id, snap(G, dests)))
    legs = {}
    for key, ps in zip(ports.port_key, port_snaps):
        for did, r in network.route_from(G, ps, dest_snaps).items():
            if r is not None:
                r["port_snap_m"], r["dest_snap_m"] = ps[1], dest_snaps[did][1]
            legs[(key, did)] = r
    return legs


def run(scenario, ports, dests, roads, p, vot):
    """All origin x destination x port options for one scenario, ranked by generalised cost.
    Returns (options DataFrame, sea legs GeoDataFrame)."""
    closed = SCENARIOS[scenario]
    rows, sea_rows = [], []
    for origin, o_lonlat in sea.ORIGINS.items():
        for _, port in ports.iterrows():
            s = sea.sea_leg(o_lonlat, (port.lon, port.lat), closed, p)
            if s is None:
                continue
            sea_rows.append(dict(scenario=scenario, origin=origin, port_key=port.port_key, nm=round(s["nm"]),
                                 sea_days=round(s["hours"] / 24, 1), sea_usd=round(s["usd"]),
                                 passages=", ".join(s["passages"]), geometry=s["geometry"]))
            port_h = port.dwell_days * 24
            port_usd = port.handling_usd_per_teu + port.dwell_days * p["storage_usd_per_teu_day"]
            for _, d in dests.iterrows():
                r = roads[(port.port_key, d.dest_id)]
                if r is None:
                    continue
                usd = s["usd"] + port_usd + r["usd"]
                hours = s["hours"] + port_h + r["hours"]
                rows.append(dict(
                    scenario=scenario, origin=origin, dest_id=d.dest_id, dest_name=d["name"], dest_type=d.type,
                    port_key=port.port_key, port_name=port["name"], port_country=port.country, sea_area=port.sea_area,
                    sea_nm=round(s["nm"]), passages=", ".join(s["passages"]),
                    road_km=round(r["length"] / 1000, 1), road_h=round(r["hours"], 1),
                    border_h=round(r["border_h"], 1), borders=", ".join(r["borders"]),
                    sea_usd=round(s["usd"]), port_usd=round(port_usd), road_usd=round(r["usd"]),
                    total_usd=round(usd), total_days=round(hours / 24, 1),
                    time_cost_usd=round(hours * vot), gen_cost_usd=round(usd + hours * vot)))
    opts = pd.DataFrame(rows)
    if len(opts):
        opts["rank"] = opts.groupby(["origin", "dest_id"]).gen_cost_usd.rank(method="first").astype(int)
    seas = gpd.GeoDataFrame(sea_rows, geometry="geometry", crs="EPSG:4326")
    return opts, seas


def compare(best, base="baseline"):
    """Each scenario's best option against the baseline's, per origin and destination."""
    b = best[best.scenario == base].set_index(["origin", "dest_id"])[["port_key", "total_usd", "total_days", "gen_cost_usd"]]
    out = best.join(b, on=["origin", "dest_id"], rsuffix="_base")
    out["port_changed"] = out.port_key != out.port_key_base
    out["extra_usd"] = out.total_usd - out.total_usd_base
    out["extra_days"] = (out.total_days - out.total_days_base).round(1)
    return out


def road_geometries(best, roads, simplify_m=50):
    """Road-leg lines for the chosen options, in EPSG:4326."""
    rows = []
    for _, r in best.iterrows():
        leg = roads[(r.port_key, r.dest_id)]
        rows.append(dict(scenario=r.scenario, origin=r.origin, port_key=r.port_key, dest_id=r.dest_id,
                         road_km=r.road_km, road_h=r.road_h, borders=r.borders,
                         geometry=leg["geometry"].simplify(simplify_m)))
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=network.CRS_WORK).to_crs("EPSG:4326")


def save(gpkg, layers):
    """Write {layer: DataFrame or GeoDataFrame} to the GeoPackage (overwriting those layers)."""
    for name, df in layers.items():
        if isinstance(df, gpd.GeoDataFrame):  # lines mix LineString/MultiLineString, so write them all as multi
            df.to_file(gpkg, layer=name, promote_to_multi=bool(df.geom_type.str.contains("Line").any()))
        else:
            import pyogrio
            pyogrio.write_dataframe(df, Path(gpkg), layer=name)
