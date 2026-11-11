"""Sea legs from origin regions to ports, using the `searoute` maritime network.

Closing a chokepoint removes it from the network; ships then take the next shortest route
(e.g. around Africa), or the port is unreachable (ports inside the Gulf when Hormuz is closed)."""
import warnings

import searoute
from shapely.geometry import LineString

ORIGINS = {  # origin region -> (lon, lat) of a representative port
    "Asia (Shanghai)": (121.8, 31.2),
    "Europe (Rotterdam)": (4.0, 51.95),
}
# searoute passage name -> cost parameter charged when a route uses it
PASSAGE_COSTS = {
    "suez": "suez_fee_usd_per_teu",
    "babalmandab": "war_risk_babalmandab_usd_per_teu",
    "ormuz": "war_risk_ormuz_usd_per_teu",
}


def route(a, b, closed=()):
    """Shortest open sea route between two (lon, lat) points: dict(nm, passages, geometry), or None
    when every route is closed. `closed`: searoute passage names (ormuz, babalmandab, suez, ...)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)  # searoute warns when no route exists
        r = searoute.searoute(list(a), list(b), units="naut", restrictions=["northwest", *closed],
                              return_passages=True)
    nm = r["properties"]["length"]
    if not nm:
        return None
    return dict(nm=nm, passages=r["properties"].get("traversed_passages") or [],
                geometry=LineString(r["geometry"]["coordinates"]))


def sea_leg(origin, port, closed, p):
    """Cheapest sea leg per TEU, or None when every route is closed.
    `origin`, `port`: (lon, lat); `closed`: searoute passage names; `p`: cost parameters."""
    r = route(origin, port, closed)
    if r is None:
        return None
    nm, passages = r["nm"], r["passages"]
    usd = nm / 1000 * p["sea_usd_per_teu_per_1000nm"] + sum(p[PASSAGE_COSTS[x]] for x in passages if x in PASSAGE_COSTS)
    return dict(nm=nm, hours=nm / p["ship_speed_knots"], usd=usd, passages=passages, geometry=r["geometry"])
