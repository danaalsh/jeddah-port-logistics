"""PortWatch charts for the Jeddah port project. Usage: python portwatch_charts.py DATA_DIR OUT_DIR
DATA_DIR holds the three PortWatch CSVs written by refresh_portwatch.py."""
import sys
from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

data, out = Path(sys.argv[1]), Path(sys.argv[2])
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
S1, S2, S3, S4 = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"   # categorical slots 1-4, fixed order
plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
    "axes.spines.left": False, "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRID,
    "grid.linewidth": 0.8, "xtick.major.size": 0, "ytick.major.size": 0,
})


def title(ax, t, sub):
    ax.set_title(t, loc="left", fontsize=12.5, fontweight="bold", color=INK, pad=24)
    ax.text(0, 1.02, sub, transform=ax.transAxes, fontsize=9.5, color=INK2, va="bottom")


def source(fig, text):
    fig.text(0.01, 0.01, text, fontsize=8, color=INK2)


names = pd.read_csv(data / "portwatch_ports_list.csv").set_index("portid").portname
ports = pd.read_csv(data / "portwatch_ports_daily_SAU.csv", parse_dates=["date"])
ports["port"] = ports.portid.map(names)   # daily file mislabels port1089 (Ras Al-Khair)
choke = pd.read_csv(data / "portwatch_chokepoints_daily.csv", parse_dates=["date"])

# 1. Chokepoint transits, 7-day average
fig, ax = plt.subplots(figsize=(10, 5.2))
series = [("Strait of Hormuz", S1), ("Bab el-Mandeb Strait", S2), ("Suez Canal", S3), ("Cape of Good Hope", S4)]
for name, color in series:
    s = choke[choke.portname == name].set_index("date").sort_index().n_total.rolling(7).mean()
    ax.plot(s.index, s, color=color, linewidth=1.6, label=name)
    ax.annotate(name.replace(" Strait", ""), (s.index[-1], s.iloc[-1]), xytext=(6, 0),
                textcoords="offset points", va="center", fontsize=9, color=INK)
ax.axvline(pd.Timestamp("2026-03-01"), color=INK2, linewidth=0.8, linestyle=":")
ax.text(pd.Timestamp("2026-03-01"), 149, " 1 Mar 2026: Hormuz\n traffic collapses", fontsize=8.5, color=INK2, va="top")
ax.axvline(pd.Timestamp("2023-12-15"), color=INK2, linewidth=0.8, linestyle=":")
ax.text(pd.Timestamp("2023-12-15"), 149, " Dec 2023: Red Sea\n diversions begin", fontsize=8.5, color=INK2, va="top")
ax.set_ylim(0, 150); ax.set_yticks(range(0, 121, 20)); ax.set_ylabel("Ships per day (7-day average)")
ax.set_xlim(pd.Timestamp("2019-01-01"), pd.Timestamp("2027-04-01"))
ax.xaxis.set_major_locator(mdates.YearLocator()); ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
ax.legend(loc="upper left", bbox_to_anchor=(0, -0.08), ncol=4, frameon=False, fontsize=9)
title(ax, "Two chokepoint shocks around Saudi Arabia",
      "Daily ship transits, all vessel types, Jan 2019 – Oct 2026")
source(fig, "Source: IMF PortWatch (AIS-based estimates). Ships transiting with AIS switched off are not counted.")
fig.tight_layout(rect=(0, 0.03, 1, 1)); fig.savefig(out / "chart_chokepoints.png", dpi=170); plt.close(fig)

# 2. Saudi port response to the Hormuz closure: monthly exports and imports (two panels, one axis each)
m = ports[(ports.date >= "2025-01-01") & (ports.date < "2026-07-01")]   # July 2026 is partial (24 days): left out
m = m.groupby([m.date.dt.to_period("M").dt.to_timestamp(), "port"])[["import", "export"]].sum() / 1e6
exp = m["export"].unstack(); imp = m["import"].unstack()
panels = [
    ("Exports (million tonnes / month)", [
        ("Yanbu, King Fahd Port (Red Sea)", exp["Yanbu (King Fahd Port)"], S1),
        ("Juaymah + Ras Tanura (Gulf)", exp["Juaymah"] + exp["Ras Tanura"], S2)]),
    ("Imports (million tonnes / month)", [
        ("Jeddah (Red Sea)", imp["Jeddah"], S1),
        ("Dammam + Jubail (Gulf)", imp["Dammam"] + imp["Jubail"], S2)]),
]
fig, axes = plt.subplots(1, 2, figsize=(11, 5.4))
for ax, (ylabel, lines) in zip(axes, panels):
    for label, s, color in lines:
        ax.plot(s.index, s, color=color, linewidth=2, marker="o", markersize=4, label=label)
        ax.annotate(f"{s.iloc[-1]:.1f}", (s.index[-1], s.iloc[-1]), xytext=(6, 0),
                    textcoords="offset points", va="center", fontsize=9, color=INK)
    ax.axvline(pd.Timestamp("2026-03-01"), color=INK2, linewidth=0.8, linestyle=":")
    ax.set_ylim(0, None); ax.set_title(ylabel, loc="left", fontsize=10.5, color=INK, pad=6)
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b\n%Y"))
    ax.legend(loc="upper left", bbox_to_anchor=(0, -0.16), ncol=1, frameon=False, fontsize=9)
fig.suptitle("Saudi trade shifted to Red Sea ports after Hormuz closed", x=0.01, ha="left",
             fontsize=12.5, fontweight="bold")
source(fig, "Source: IMF PortWatch port-level trade estimates, Jan 2025 – Jun 2026 (July 2026 incomplete, omitted). "
            "Dotted line: 1 Mar 2026.")
fig.tight_layout(rect=(0, 0.04, 1, 0.97)); fig.savefig(out / "chart_hormuz_port_shift.png", dpi=170); plt.close(fig)

# 3. What each port exports, by vessel type (12 months before the Hormuz shock)
w = ports[(ports.date >= "2025-03-01") & (ports.date < "2026-03-01")].groupby("port").sum(numeric_only=True)
mix = pd.DataFrame({
    "Tanker (crude, refined, liquid chemicals)": w.export_tanker,
    "Dry bulk (fertilizer, minerals, metals)": w.export_dry_bulk,
    "Container (manufactured goods, packed chemicals)": w.export_container,
    "General cargo and RoRo": w.export_general_cargo + w.export_roro,
})
total = mix.sum(axis=1)
order = ["Juaymah", "Yanbu (King Fahd Port)", "Jubail", "Ras Tanura", "Jeddah", "Rabigh",
         "Ras Al-Khair", "Dammam", "Yanbu (Yanbu city)", "King Abdullah Port"]
share = mix.loc[order].div(total.loc[order], axis=0) * 100
fig, ax = plt.subplots(figsize=(10, 5.4))
left = pd.Series(0.0, index=order)
for (label, col), color in zip(share.items(), (S1, S2, S3, S4)):
    ax.barh(order, col, left=left, color=color, height=0.62, label=label, edgecolor=SURFACE, linewidth=2)
    for i, (p, v) in enumerate(col.items()):
        if v >= 12:
            ax.text(left[p] + v / 2, i, f"{v:.0f}%", ha="center", va="center", fontsize=8.5,
                    color="white" if color in (S1, S2) else INK)
    left += col
for i, p in enumerate(order):
    ax.text(101.5, i, f"{total[p] / 1e6:.0f} Mt", va="center", fontsize=9, color=INK2)
ax.text(101.5, -0.85, "exports", fontsize=8.5, color=INK2)
ax.invert_yaxis(); ax.set_xlim(0, 112); ax.grid(False)
ax.set_xticks([0, 25, 50, 75, 100]); ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"])
ax.legend(loc="upper left", bbox_to_anchor=(0, -0.07), ncol=2, frameon=False, fontsize=9)
title(ax, "Jeddah exports containers; bulk and tankers leave elsewhere",
      "Share of each port's export tonnage by vessel type, Mar 2025 – Feb 2026 (before the Hormuz closure)")
source(fig, "Source: IMF PortWatch. Vessel type is a proxy for commodity; product-level detail needs GASTAT trade-by-port data.")
fig.tight_layout(rect=(0, 0.03, 1, 1)); fig.savefig(out / "chart_export_mix.png", dpi=170); plt.close(fig)
print("charts written to", out)
