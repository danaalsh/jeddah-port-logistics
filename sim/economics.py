"""Economic impact: per-TEU route costs scaled up by annual container volumes.

Annual TEU bound for industrial cities = Saudi container imports (PortWatch, tonnes) / tonnes per TEU
x share bound for industrial cities, split between cities by active area (developed x occupancy) and
between origins by the origin shares. Impact of a scenario = its annual cost minus the baseline's.
"""
import pandas as pd

ORIGIN_SHARE_PARAMS = {"Asia (Shanghai)": "asia_share_of_container_imports"}


def container_imports_tonnes(pw_daily, end, months=12):
    """Saudi container imports (tonnes per year) in the `months` before `end`, from PortWatch daily data."""
    pw = pw_daily.assign(date=pd.to_datetime(pw_daily.date))
    start = pd.Timestamp(end) - pd.DateOffset(months=months)
    return pw[(pw.date >= start) & (pw.date < pd.Timestamp(end))].import_container.sum() * 12 / months


def volumes(dests, imports_t, p, origins):
    """Annual TEU per (dest_id, origin) for industrial cities."""
    ind = dests[dests.type == "industrial_city"]
    total_teu = imports_t / p["tonnes_per_teu"] * p["industrial_share_of_container_imports"]
    asia = p["asia_share_of_container_imports"]
    share = {o: (asia if ORIGIN_SHARE_PARAMS.get(o) else 1 - asia) for o in origins}
    rows = [dict(dest_id=d.dest_id, origin=o, teu=total_teu * d.active_m2 / ind.active_m2.sum() * s)
            for _, d in ind.iterrows() for o, s in share.items()]
    return pd.DataFrame(rows)


def impacts(best, vols, vot):
    """Annual cost per scenario, origin and destination, and the change against the baseline."""
    df = best.merge(vols, on=["dest_id", "origin"])
    hours = df.total_days * 24
    df["annual_usd"] = df.teu * df.total_usd                 # money paid for transport, ports, borders
    df["annual_time_cost_usd"] = df.teu * hours * vot        # inventory cost of time in transit
    df["annual_teu_days"] = df.teu * df.total_days
    base = df[df.scenario == "baseline"].set_index(["origin", "dest_id"])
    for c in ("annual_usd", "annual_time_cost_usd", "annual_teu_days"):
        df["extra_" + c] = df[c] - df.join(base[c], on=["origin", "dest_id"], rsuffix="_b")[c + "_b"]
    return df


def summarise(imp, by=("scenario",)):
    """Totals per scenario (and optionally region/origin): annual cost, extra cost, extra TEU-days."""
    g = imp.groupby(list(by))
    out = pd.DataFrame({
        "teu_per_year": g.teu.sum(),
        "annual_cost_usd_m": g.annual_usd.sum() / 1e6,
        "extra_cost_usd_m": g.extra_annual_usd.sum() / 1e6,
        "extra_time_cost_usd_m": g.extra_annual_time_cost_usd.sum() / 1e6,
        "extra_teu_days_k": g.extra_annual_teu_days.sum() / 1e3,
    })
    out["extra_cost_pct"] = 100 * out.extra_cost_usd_m / (out.annual_cost_usd_m - out.extra_cost_usd_m)
    return out.round(1)
