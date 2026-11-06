"""GCC road network: build the graph, add truck costs and border delays, route on it.

Costs are per TEU (one twenty-foot container). Each edge carries:
  length   metres
  hours    truck driving time, plus any border delay on the edge
  usd      truck operating cost per TEU, plus border fees
  gc       generalised cost = usd + hours * value of cargo time; routes minimise this
"""
from pathlib import Path
import pickle

import networkx as nx
import osmium
import osmnx as ox
import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString, Point
from shapely.ops import linemerge, substring
from shapely.strtree import STRtree

# Lambert conformal conic fitted to the Arabian Peninsula: metres, low distortion from Jordan to Oman
CRS_WORK = "+proj=lcc +lat_1=17 +lat_2=27 +lat_0=22 +lon_0=48 +datum=WGS84 +units=m +no_defs"


def pbf_to_xml(pbf, xml):
    """OSMnx reads OSM XML; convert the (small, filtered) PBF once."""
    xml = Path(xml)
    if not xml.exists():
        with osmium.SimpleWriter(str(xml), overwrite=True) as w:
            for obj in osmium.FileProcessor(str(pbf)):
                w.add(obj)
    return xml


def build_graph(pbf, cache_dir, truck_max_kph):
    """Strongly connected, projected road graph with car and truck free-flow times. Cached."""
    cache = Path(cache_dir) / f"gcc_graph_truck{truck_max_kph}.pkl"
    if cache.exists() and cache.stat().st_mtime > Path(pbf).stat().st_mtime:
        return pickle.loads(cache.read_bytes())
    xml = pbf_to_xml(pbf, Path(cache_dir) / "gcc_major.osm")
    G = ox.graph_from_xml(xml, simplify=True, retain_all=True)
    G = ox.truncate.largest_component(G, strongly=True)
    G = ox.add_edge_speeds(G)
    fix_speeds(G, truck_max_kph)
    G = ox.project_graph(G, to_crs=CRS_WORK)
    cache.write_bytes(pickle.dumps(G))
    return G


def fix_speeds(G, truck_max_kph):
    """Replace missing or zero speeds (OSM tagging errors such as maxspeed=0) with their road
    class's mean, then set car (travel_time) and truck (truck_tt) seconds."""
    by_class = {}
    for _, _, d in G.edges(data=True):
        if d["speed_kph"] > 0:
            by_class.setdefault(str(d.get("highway")), []).append(d["speed_kph"])
    mean = {k: sum(v) / len(v) for k, v in by_class.items()}
    overall = sum(map(sum, by_class.values())) / sum(map(len, by_class.values()))
    for _, _, d in G.edges(data=True):
        if not d["speed_kph"] > 0:
            d["speed_kph"] = mean.get(str(d.get("highway")), overall)
        d["travel_time"] = d["length"] / (d["speed_kph"] / 3.6)
        d["truck_tt"] = d["length"] / (min(d["speed_kph"], truck_max_kph) / 3.6)


def edge_line(G, u, v, k):
    d = G.edges[u, v, k]
    if "geometry" in d:
        return d["geometry"]
    return LineString([(G.nodes[u]["x"], G.nodes[u]["y"]), (G.nodes[v]["x"], G.nodes[v]["y"])])


def to_work(lon, lat):
    """lon/lat arrays -> x/y arrays in CRS_WORK."""
    pts = gpd.GeoSeries(gpd.points_from_xy(lon, lat), crs="EPSG:4326").to_crs(CRS_WORK)
    return pts.x.to_numpy(), pts.y.to_numpy()


def add_border_delays(G, crossings):
    """Charge each border crossing's delay and fee to the roads through it.

    A crossing is a circle (lat, lon, radius_m) around its border posts. An edge pays half the
    crossing's delay and fee for every time it cuts the circle's edge, so a route through the
    crossing (in once, out once) pays it once, whichever lanes it uses. Each cut is stored with
    its position along the edge ("cuts"), so a route using only part of an edge pays only for
    the cuts it passes."""
    for _, _, d in G.edges(data=True):
        d["border_h"], d["border_fee_truck"], d["border_name"], d["cuts"] = 0.0, 0.0, "", []
    keys = list(G.edges(keys=True))
    lines = [edge_line(G, *k) for k in keys]
    tree = STRtree(lines)
    xs, ys = to_work(crossings.lon, crossings.lat)
    report = []
    for (_, c), x, y in zip(crossings.iterrows(), xs, ys):
        ring = Point(x, y).buffer(c.radius_m).exterior
        n_edges = 0
        for i in tree.query(ring):
            hits = lines[i].intersection(ring)
            pts = [] if hits.is_empty else list(getattr(hits, "geoms", [hits]))
            if pts:
                d = G.edges[keys[i]]
                for pt in pts:
                    d["cuts"].append((lines[i].project(pt, normalized=True),
                                      dict(border_h=c.delay_h / 2, fee=c.fee_usd_per_truck / 2, name=c["name"])))
                d["border_h"] += len(pts) / 2 * c.delay_h
                d["border_fee_truck"] += len(pts) / 2 * c.fee_usd_per_truck
                d["border_name"] = c["name"]
                n_edges += 1
        report.append((c["name"], n_edges))
    return pd.DataFrame(report, columns=["crossing", "edges_charged"])


def set_costs(G, p):
    """Per-TEU hours, money and generalised cost on every edge. `p` maps cost parameter -> value."""
    teu = p["truck_teu_per_truck"]
    vot = p["cargo_value_usd_per_teu"] * p["holding_rate_per_year"] / 8760  # USD per TEU-hour
    for _, _, d in G.edges(data=True):
        drive_h = d["truck_tt"] / 3600
        d["hours"] = drive_h + d["border_h"]
        d["usd"] = (d["length"] / 1000 * p["truck_usd_per_km"] + d["hours"] * p["truck_usd_per_hour"]
                    + d["border_fee_truck"]) / teu
        d["gc"] = d["usd"] + d["hours"] * vot
        for _, c in d.get("cuts", []):  # each cut's own share, for partial edges
            c["hours"] = c["border_h"]
            c["usd"] = (c["border_h"] * p["truck_usd_per_hour"] + c["fee"]) / teu
            c["gc"] = c["usd"] + c["border_h"] * vot
    return vot


def partial(d, key, s0, s1):
    """Edge attribute `key` for the stretch from fraction s0 to s1: distance-based parts pro rata,
    border delays and fees only for the crossing cuts inside the stretch."""
    if s0 == 0 and s1 == 1:
        return d[key]
    cuts = d.get("cuts", [])
    base = d[key] - sum(c.get(key, 0.0) for _, c in cuts)
    return (s1 - s0) * base + sum(c.get(key, 0.0) for f, c in cuts if s0 <= f <= s1)


def snap_points(G, xs, ys):
    """Snap points onto their nearest road segment. For each point returns
    ([(u, v, k, fraction along edge), ...], snap distance in m); the list holds
    both directions of a two-way road."""
    edges, dists = ox.distance.nearest_edges(G, xs, ys, return_dist=True)
    out = []
    for (u, v, _), dist, x, y in zip(edges, dists, xs, ys):
        p, on = Point(x, y), []
        for a, b in {(u, v), (v, u)}:
            for k in G[a][b] if G.has_edge(a, b) else []:
                line = edge_line(G, a, b, k)
                if line.distance(p) <= dist + 1:  # same road, not a parallel one
                    on.append((a, b, k, line.project(p, normalized=True)))
        out.append((on, float(dist)))
    return out


SUMS = ("gc", "hours", "usd", "length", "border_h")


def route_from(G, origin, targets, weight="gc"):
    """Cheapest routes by `weight` from one snapped origin to many snapped targets ({id: snap}).
    Routes start and end part-way along their edges. Returns {id: dict(geometry, gc, hours, usd,
    length, border_h, borders)} or None for unreachable targets."""
    start = {}
    for a, b, k, f in origin[0]:  # leave the origin edge through its far end
        c = partial(G.edges[a, b, k], weight, f, 1.0)
        if b not in start or c < start[b][0]:
            start[b] = (c, (a, b, k, f))
    SRC = "__origin__"
    G.add_node(SRC)
    for b, (c, _) in start.items():
        G.add_edge(SRC, b, **{weight: c})
    try:
        cost, paths = nx.single_source_dijkstra(G, SRC, weight=weight)
    finally:
        G.remove_node(SRC)

    out = {}
    for tid, (on, _) in targets.items():
        reach = [(cost[a] + partial(G.edges[a, b, k], weight, 0.0, g), a, b, k, g) for a, b, k, g in on if a in cost]
        if not reach:
            out[tid] = None
            continue
        _, a, b, k, g = min(reach)
        nodes = paths[a][1:]
        oa, ob, ok_, f = start[nodes[0]][1]
        legs = [((oa, ob, ok_), f, 1.0)]
        legs += [((u, v, min(G[u][v], key=lambda key: G[u][v][key][weight])), 0.0, 1.0)
                 for u, v in zip(nodes[:-1], nodes[1:])]
        legs.append(((a, b, k), 0.0, g))
        r = dict.fromkeys(SUMS, 0.0)
        parts, borders = [], []
        for e, s0, s1 in legs:
            d = G.edges[e]
            for key in SUMS:
                r[key] += partial(d, key, s0, s1)
            for f, c in d.get("cuts", []):
                if s0 <= f <= s1 and c["name"] not in borders:
                    borders.append(c["name"])
            part = substring(edge_line(G, *e), s0, s1, normalized=True)
            if part.geom_type == "LineString" and part.length > 0:
                parts.append(part)
        r["geometry"] = linemerge(parts)
        r["borders"] = borders
        out[tid] = r
    return out
