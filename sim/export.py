"""Export the model to the browser simulator (simulator/template.html -> one self-contained page).

The page re-ranks ports in the browser, so it gets the cost *ingredients*, not costs:
  sea legs   for every combination of closed passages: nautical miles, passages used, line
  road legs  for every port and destination: km, driving hours, borders crossed, line
             (paths are fixed at the default costs; sliders re-cost them but do not re-route)
plus ports, destinations with weights, cost defaults and volumes. Coordinates are rounded and
lines simplified to keep the page small.
"""
from itertools import combinations
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import mapping
from shapely.ops import linemerge

from . import network, sea

CLOSABLE = ["ormuz", "babalmandab", "suez"]  # searoute passage names the page can close


def _coords(geom, ndigits=3):
    """[[lon, lat], ...] or list of those for multi-part lines, rounded."""
    g = mapping(geom)
    r = lambda pts: [[round(x, ndigits), round(y, ndigits)] for x, y in pts]
    return r(g["coordinates"]) if g["type"] == "LineString" else [r(part) for part in g["coordinates"]]


def _to_lonlat(geom_work, tolerance_m):
    s = gpd.GeoSeries([geom_work.simplify(tolerance_m)], crs=network.CRS_WORK).to_crs("EPSG:4326")
    return s.iloc[0]


def sea_legs(ports, p):
    """{closure key: {origin: {port_key: leg or None}}}; key is the closed passages joined by '+', '' for none."""
    out = {}
    for n in range(len(CLOSABLE) + 1):
        for closed in combinations(CLOSABLE, n):
            key = "+".join(closed)
            out[key] = {}
            for origin, o_lonlat in sea.ORIGINS.items():
                out[key][origin] = {}
                for _, port in ports.iterrows():
                    s = sea.sea_leg(o_lonlat, (port.lon, port.lat), list(closed), p)
                    out[key][origin][port.port_key] = None if s is None else dict(
                        nm=round(s["nm"]), passages=s["passages"], line=_coords(s["geometry"].simplify(0.05), 2))
    return out


def road_legs(roads, tolerance_m=1500):
    """{port_key: {dest_id: leg}} with km, driving hours (no border time), borders, line."""
    out = {}
    for (port_key, dest_id), r in roads.items():
        if r is None:
            continue
        out.setdefault(port_key, {})[dest_id] = dict(
            km=round(r["length"] / 1000, 1), drive_h=round(r["hours"] - r["border_h"], 2), borders=r["borders"],
            line=_coords(_to_lonlat(r["geometry"], tolerance_m)))
    return out


def context_roads(G, tolerance_m=2000):
    """Motorways and trunk roads as a light background layer (lon/lat line lists)."""
    lines = []
    for u, v, k, d in G.edges(keys=True, data=True):
        hw = d.get("highway")
        hw = hw[0] if isinstance(hw, list) else hw
        if hw in ("motorway", "trunk") and (u < v or not G.has_edge(v, u)):  # each two-way road once
            lines.append(network.edge_line(G, u, v, k))
    merged = linemerge(lines)
    parts = list(getattr(merged, "geoms", [merged]))
    s = gpd.GeoSeries(parts, crs=network.CRS_WORK).simplify(tolerance_m).to_crs("EPSG:4326")
    return [_coords(g) for g in s if g.length > 0]


def countries(shapefile, bbox=(-25, -40, 135, 62), tolerance_deg=0.05):
    """Natural Earth countries clipped to the map area, as a GeoJSON FeatureCollection."""
    w = gpd.read_file(shapefile)[["name", "iso_a3", "geometry"]].clip(bbox)
    w["geometry"] = w.simplify(tolerance_deg)
    return json.loads(w.to_json(drop_id=True, to_wgs84=True).replace(".0,", ","))


def build(path_template, path_out, *, G, ports, dests, roads, p, crossings, imports_t, countries_shp, meta):
    """Fill the simulator template with the model data and write the page."""
    data = dict(
        meta=meta,
        params={k: float(v) for k, v in p.items()},
        imports_tonnes=float(imports_t),
        origins=list(sea.ORIGINS),
        ports=json.loads(ports[["port_key", "name", "country", "sea_area", "handling_usd_per_teu", "dwell_days",
                                "lat", "lon"]].to_json(orient="records")),
        dests=json.loads(dests[["dest_id", "name", "type", "region", "lat", "lon", "active_m2", "location_method"]]
                         .assign(region=lambda d: d.region.fillna(""), active_m2=lambda d: d.active_m2.fillna(0),
                                 location_method=lambda d: d.location_method.fillna(""))
                         .to_json(orient="records")),
        crossings=json.loads(crossings[["name", "countries", "delay_h", "fee_usd_per_truck"]].to_json(orient="records")),
        sea=sea_legs(ports, p),
        road=road_legs(roads),
        context_roads=context_roads(G),
        countries=countries(countries_shp),
    )
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")  # safe inside <script>
    page = Path(path_template).read_text().replace("/*SIM_DATA*/null", blob)
    Path(path_out).write_text(page)
    return len(page)
