"""Export route options: production site -> land leg (truck or pipeline) -> export port -> sea -> market.

Costs are per tonne. Each option also gets a risk score (0-100) built from two data signals:
  disruption  how far traffic through each strait on the route has fallen against 2023 (IMF PortWatch)
  tension     the Geopolitical Risk Index (Caldara and Iacoviello): latest global and Saudi readings as
              percentiles of their own history; weighs most on routes through Middle East straits
and from border crossings on the land leg. War-risk insurance is priced from the same two signals.
"Today" closes any strait whose traffic is down by at least `closed_threshold` and uses today's
disruption for risk and insurance; "normal" closes none and assumes no disruption (GPR still applies).
"""
from math import prod
from pathlib import Path

import pandas as pd
from shapely.geometry import LineString

from . import network, sea

CLOSABLE = ["ormuz", "babalmandab", "suez"]
MIDDLE_EAST = {"ormuz", "babalmandab", "suez"}
PASSAGES = {  # searoute name -> (label, PortWatch chokepoint name)
    "ormuz": ("Strait of Hormuz", "Strait of Hormuz"),
    "babalmandab": ("Bab el-Mandeb", "Bab el-Mandeb Strait"),
    "suez": ("Suez Canal", "Suez Canal"),
    "malacca": ("Malacca Strait", "Malacca Strait"),
    "gibraltar": ("Strait of Gibraltar", "Gibraltar Strait"),
    "south_africa": ("Cape of Good Hope", "Cape of Good Hope"),
    "sunda": ("Sunda Strait", "Sunda Strait"),
    "panama": ("Panama Canal", "Panama Canal"),
    "bosporus": ("Bosporus", "Bosporus Strait"),
}
GPR_WEIGHT = {"me": 0.3, "other": 0.1}  # share of GPR tension added to a passage's risk
BORDER_RISK = 0.05                       # per border crossing on the land leg


def load_config(cfg_dir):
    cfg = Path(cfg_dir)
    c = pd.read_csv(cfg / "costs.csv")
    return dict(
        p=dict(zip(c.parameter, c.value.astype(float))),
        commodities=pd.read_csv(cfg / "commodities.csv"),
        sites=pd.read_csv(cfg / "sites.csv"),
        markets=pd.read_csv(cfg / "markets.csv"),
        ports=pd.read_csv(cfg / "ports.csv"),
        pipelines=pd.read_csv(cfg / "pipelines.csv"),
    )


def disruption(choke, recent_days=28, base=("2023-01-01", "2023-11-01")):
    """Per searoute passage: share by which daily transits in the last `recent_days` are below the
    pre-Red-Sea-crisis 2023 average (0 = normal or busier, 1 = no traffic), with the two averages."""
    c = choke.assign(date=pd.to_datetime(choke.date))
    last = c.date.max()
    recent = c[c.date > last - pd.Timedelta(days=recent_days)].groupby("portname").n_total.mean()
    before = c[(c.date >= base[0]) & (c.date < base[1])].groupby("portname").n_total.mean()
    out = {}
    for key, (label, pw_name) in PASSAGES.items():
        if pw_name in before and pw_name in recent and before[pw_name] > 0:
            out[key] = dict(label=label, base=round(before[pw_name], 1), recent=round(recent[pw_name], 1),
                            disruption=round(max(0.0, 1 - recent[pw_name] / before[pw_name]), 3))
    return out, str(last.date())


def gpr_levels(xls):
    """Latest monthly global GPR and Saudi GPR (GPRC_SAU), with percentiles of their history since 1985.
    Returns None if the file is missing or has neither column."""
    if xls is None or not Path(xls).exists():
        return None
    g = pd.read_excel(xls)
    month = next((c for c in g.columns if str(c).lower() == "month"), g.columns[0])
    g[month] = pd.to_datetime(g[month])
    g = g[g[month] >= "1985-01-01"]
    out = {}
    for col, key in (("GPR", "global"), ("GPRC_SAU", "saudi")):
        if col in g:
            s = g[[month, col]].dropna()
            latest = s.iloc[-1]
            out[key] = dict(value=round(float(latest[col]), 1), month=str(latest[month].date())[:7],
                            percentile=round(float((s[col] <= latest[col]).mean() * 100), 1),
                            mean=round(float(s[col].mean()), 1))
    return out or None


def tension(gpr):
    """0-1 geopolitical tension: mean of the available GPR percentiles; 0 when GPR is not loaded."""
    if not gpr:
        return 0.0
    return sum(v["percentile"] for v in gpr.values()) / len(gpr) / 100


def gpr_price_multiplier(gpr):
    """War-risk base premium scales with global GPR relative to its long-run mean (1 when not loaded)."""
    return gpr["global"]["value"] / gpr["global"]["mean"] if gpr and "global" in gpr else 1.0


def conditions(dis, p):
    """Closed passages for each condition."""
    return {"normal": [], "today": [k for k in CLOSABLE if dis.get(k, {}).get("disruption", 0) >= p["closed_threshold"]]}


def land_legs(G, sites, ports, pipelines, border_crossings):
    """{(site_id, port_key): leg}. Truck legs on the road graph (G needs costs set); pipeline legs from config."""
    delay = dict(zip(border_crossings.name, border_crossings.delay_h))
    fee = dict(zip(border_crossings.name, border_crossings.fee_usd_per_truck))
    xs, ys = network.to_work(ports.lon, ports.lat)
    port_snaps = dict(zip(ports.port_key, network.snap_points(G, xs, ys)))
    sx, sy = network.to_work(sites.lon, sites.lat)
    legs = {}
    for (_, s), snap in zip(sites.iterrows(), network.snap_points(G, sx, sy)):
        for pk, r in network.route_from(G, snap, port_snaps).items():
            if r is None:
                continue
            legs[(s.site_id, pk)] = dict(
                mode="truck", km=r["length"] / 1000, drive_h=r["hours"] - r["border_h"], borders=r["borders"],
                border_h=sum(delay[b] for b in r["borders"]), border_fee_truck=sum(fee[b] for b in r["borders"]),
                geometry=gpd_to_lonlat(r["geometry"]))
    site_pt = sites.set_index("site_id")[["lon", "lat"]]
    port_pt = ports.set_index("port_key")[["lon", "lat"]]
    for _, pl in pipelines.iterrows():
        legs[(pl.site_id, pl.port_key, "pipeline")] = dict(
            mode="pipeline", name=pl["name"], km=float(pl.km), borders=[],
            geometry=LineString([tuple(site_pt.loc[pl.site_id]), tuple(port_pt.loc[pl.port_key])]))
    return legs


def gpd_to_lonlat(geom_work, tolerance_m=1500):
    import geopandas as gpd
    return gpd.GeoSeries([geom_work.simplify(tolerance_m)], crs=network.CRS_WORK).to_crs("EPSG:4326").iloc[0]


def sea_legs(ports, markets, closures):
    """{(condition, port_key, market_id): route or None}."""
    out = {}
    for cond, closed in closures.items():
        for _, port in ports.iterrows():
            for _, m in markets.iterrows():
                out[(cond, port.port_key, m.market_id)] = sea.route((port.lon, port.lat), (m.lon, m.lat), closed)
    return out


def _risk(passages, n_borders, dis, t):
    """Risk score 0-100 and the reasons behind it."""
    parts, reasons = [], []
    for x in passages:
        d = dis.get(x, {}).get("disruption", 0.0)
        w = GPR_WEIGHT["me" if x in MIDDLE_EAST else "other"]
        parts.append(1 - (1 - d) * (1 - w * t))
        if d >= 0.05:
            reasons.append(f"{PASSAGES[x][0]}: traffic down {d * 100:.0f}% on 2023")
        elif x in MIDDLE_EAST:
            reasons.append(f"{PASSAGES[x][0]}: traffic normal; Middle East strait")
    if n_borders:
        reasons.append(f"{n_borders} border crossing{'s' if n_borders > 1 else ''} by truck")
    score = 100 * (1 - prod(1 - r for r in parts) * (1 - BORDER_RISK) ** n_borders)
    return round(score), reasons


def options(cfg, land, seas, dis, gpr, closures):
    """Every feasible (site, commodity, market, condition, port) option, plus blocked ones for 'today'."""
    p, t, mult = cfg["p"], tension(gpr), gpr_price_multiplier(gpr)
    com = cfg["commodities"].set_index("commodity_id")
    ports = cfg["ports"].set_index("port_key")
    rows = []
    for _, s in cfg["sites"].iterrows():
        for cid in s.commodities.split("|"):
            c = com.loc[cid]
            for pk, port in ports.iterrows():
                if c["mode"] not in port.modes.split("|"):
                    continue
                leg = land.get((s.site_id, pk, "pipeline")) if c.land == "pipeline" else land.get((s.site_id, pk))
                if leg is None or (c.land == "truck" and leg["mode"] != "truck"):
                    continue
                for cond in closures:
                    dis_c = dis if cond == "today" else {}  # normal: no observed disruption
                    for _, m in cfg["markets"].iterrows():
                        r = seas[(cond, pk, m.market_id)]
                        base = dict(site_id=s.site_id, commodity_id=cid, market_id=m.market_id, condition=cond,
                                    port_key=pk, land_mode=leg["mode"])
                        if r is None:
                            if cond == "today" and seas[("normal", pk, m.market_id)] is not None:
                                blocked = [PASSAGES[x][0] for x in closures[cond]]
                                rows.append({**base, "status": "blocked",
                                             "reasons": [f"Closed today: {', '.join(blocked)}"]})
                            continue
                        rows.append({**base, "status": "open", **_cost(c, leg, r, p, dis_c, mult),
                                     **dict(zip(("risk", "reasons"),
                                                _risk(r["passages"], len(leg["borders"]), dis_c, t)))})
    return pd.DataFrame(rows)


def _cost(c, leg, r, p, dis, mult):
    mode, value = c["mode"], float(c.value_usd_per_t)
    if leg["mode"] == "pipeline":
        land_usd = leg["km"] / 100 * p["pipeline_usd_per_t_per_100km"]
        land_h = leg["km"] / p["pipeline_kmh"]
        border_usd = 0.0
    else:
        land_usd = leg["km"] * p["truck_usd_per_t_km"] + leg["drive_h"] * p["truck_usd_per_t_hour"]
        border_usd = leg["border_h"] * p["truck_usd_per_t_hour"] + leg["border_fee_truck"] / p["truck_t_per_truck"]
        land_h = leg["drive_h"] + leg["border_h"]
    port_usd, port_h = p[f"port_usd_per_t_{mode}"], p[f"port_days_{mode}"] * 24
    sea_usd = r["nm"] / 1000 * p[f"sea_usd_per_t_per_1000nm_{mode}"]
    sea_h = r["nm"] / p[f"ship_speed_knots_{mode}"]
    suez_usd = p["suez_fee_usd_per_t"] if "suez" in r["passages"] else 0.0
    war_pct = sum(p["war_risk_base_pct"] * mult + p["war_risk_surge_pct"] * dis.get(x, {}).get("disruption", 0.0)
                  for x in r["passages"] if x in MIDDLE_EAST)
    war_usd = value * war_pct / 100
    days = (land_h + port_h + sea_h) / 24
    total = land_usd + border_usd + port_usd + sea_usd + suez_usd + war_usd
    return dict(land_km=round(leg["km"]), sea_nm=round(r["nm"]), passages=r["passages"], borders=leg["borders"],
                land_usd=round(land_usd, 2), border_usd=round(border_usd, 2), port_usd=round(port_usd, 2),
                sea_usd=round(sea_usd, 2), canal_usd=round(suez_usd, 2), war_risk_usd=round(war_usd, 2),
                total_usd=round(total, 2), days=round(days, 1),
                time_cost_usd=round(value * p["holding_rate_per_year"] * days / 365, 2))


def page_data(cfg, land, seas, dis, gpr, closures, opts, meta, countries_geojson):
    """Everything the planner page needs, as one JSON-ready dict (lines as [lon, lat] lists)."""
    from .export import _coords
    import json
    used_land = {(r.site_id, r.port_key, r.land_mode) for r in opts.itertuples()}
    used_sea = {(r.condition, r.port_key, r.market_id) for r in opts[opts.status == "open"].itertuples()}
    land_lines = {}
    for key, leg in land.items():
        site, port = key[0], key[1]
        mode = "pipeline" if len(key) == 3 else "truck"
        if (site, port, mode) in used_land:
            land_lines[f"{site}|{port}|{mode}"] = _coords(leg["geometry"])
    sea_lines = {f"{c}|{p}|{m}": _coords(r["geometry"].simplify(0.05), 2)
                 for (c, p, m), r in seas.items() if r is not None and (c, p, m) in used_sea}
    o = opts.copy()
    for col in ("passages", "borders", "reasons"):
        o[col] = o[col].map(lambda v: v if isinstance(v, list) else [])
    o = o.where(o.notna(), None)
    pipes = {f"{r.site_id}|{r.port_key}": r["name"] for _, r in cfg["pipelines"].iterrows()}
    return dict(
        meta=meta,
        params=cfg["p"],
        commodities=json.loads(cfg["commodities"].to_json(orient="records")),
        sites=json.loads(cfg["sites"][["site_id", "name", "type", "lat", "lon", "commodities"]].to_json(orient="records")),
        markets=json.loads(cfg["markets"].to_json(orient="records")),
        ports=json.loads(cfg["ports"][["port_key", "name", "country", "sea_area", "lat", "lon"]].to_json(orient="records")),
        pipelines=pipes,
        options=json.loads(o.to_json(orient="records")),
        disruption=dis, gpr=gpr, closures=closures,
        passage_labels={k: v[0] for k, v in PASSAGES.items()},
        land_lines=land_lines, sea_lines=sea_lines,
        countries=countries_geojson,
    )


def build_page(template, out, data):
    """Write the planner page: the template with the data embedded."""
    import json
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")  # safe inside <script>
    page = Path(template).read_text().replace("/*PLANNER_DATA*/null", blob)
    Path(out).write_text(page)
    return len(page)
