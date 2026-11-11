"""MODON industrial cities data (March 2026) -> config/industrial_cities_modon.csv with locations.

Locations, in order of reliability (column `location_method`):
  osm_name_match     OSM industrial area named as this MODON city (centre of the area)
  osm_probable       OSM industrial area of plausible size in the right town, not named as the city; verify
  town_centre        no OSM area found; approximate town centre; verify
English names are translations by Claude. Usage (from the repository root):
  python scripts/modon_cities.py CITIES_XLSX gcc_extras.osm.pbf config/industrial_cities_modon.csv
gcc_extras.osm.pbf comes from the data-latest release."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sim import places  # noqa: E402

# Row order of the MODON sheet: (English name, region, location method, OSM area id or None, lat, lon)
# lat/lon are used only when there is no OSM id.
CITIES = [
    ("Riyadh 1st Industrial City", "Riyadh", "osm_probable", 714489386, None, None),
    ("Riyadh 2nd Industrial City", "Riyadh", "osm_probable", 36947298, None, None),
    ("Riyadh 3rd Industrial City", "Riyadh", "town_centre", None, 24.71, 46.68),
    ("Al-Kharj Industrial City", "Riyadh", "osm_name_match", 336122494, None, None),
    ("Sudair City for Industry and Business", "Riyadh", "osm_name_match", 968897611, None, None),
    ("Al-Zulfi Industrial City", "Riyadh", "osm_name_match", 733877524, None, None),
    ("Shaqra Industrial City", "Riyadh", "town_centre", None, 25.25, 45.25),
    ("Dhurma Industrial City", "Riyadh", "osm_probable", 332359672, None, None),
    ("Jeddah 1st Industrial City", "Makkah", "osm_name_match", 1227500250, None, None),
    ("Jeddah 2nd Industrial City", "Makkah", "osm_name_match", 805792326, None, None),
    ("Jeddah 3rd Industrial City", "Makkah", "osm_name_match", 1358981191, None, None),
    ("Modon Oasis Jeddah", "Makkah", "osm_name_match", 1371837215, None, None),
    ("Makkah 1st Industrial City", "Makkah", "osm_name_match", 1372643537, None, None),
    ("Makkah 2nd Industrial City", "Makkah", "town_centre", None, 21.42, 39.83),
    ("Taif Industrial City", "Makkah", "osm_probable", 1183927993, None, None),
    ("Rabigh Industrial City", "Makkah", "town_centre", None, 22.80, 39.03),
    ("Madinah Industrial City", "Madinah", "town_centre", None, 24.47, 39.61),
    ("Modon Oasis Yanbu", "Madinah", "town_centre", None, 24.09, 38.06),
    ("Qassim 1st Industrial City", "Qassim", "osm_name_match", 59445653, None, None),
    ("Qassim 2nd Industrial City", "Qassim", "town_centre", None, 26.33, 43.97),
    ("Modon Oasis Qassim", "Qassim", "osm_name_match", 815409479, None, None),
    ("Dammam 1st Industrial City", "Eastern Province", "osm_name_match", 1242258034, None, None),
    ("Dammam 2nd Industrial City", "Eastern Province", "osm_name_match", 95206468, None, None),
    ("Dammam 3rd Industrial City", "Eastern Province", "town_centre", None, 26.43, 50.10),
    ("Al-Ahsa 1st Industrial City", "Eastern Province", "town_centre", None, 25.38, 49.59),
    ("Modon Oasis Al-Ahsa", "Eastern Province", "town_centre", None, 25.38, 49.59),
    ("Hafar Al-Batin Industrial City", "Eastern Province", "town_centre", None, 28.43, 45.96),
    ("Modon Oasis Aseer", "Aseer", "town_centre", None, 18.30, 42.73),
    ("Aseer Industrial City", "Aseer", "town_centre", None, 18.22, 42.50),
    ("Tabuk Industrial City", "Tabuk", "town_centre", None, 28.38, 36.57),
    ("Ha'il Industrial City", "Ha'il", "osm_name_match", 556812101, None, None),
    ("Waad Al-Shamal City for Mining Industries", "Northern Borders", "osm_probable", 882569203, None, None),
    ("Arar Industrial City", "Northern Borders", "town_centre", None, 30.98, 41.04),
    ("Jazan Industrial City", "Jazan", "osm_name_match", 388980144, None, None),
    ("Najran Industrial City", "Najran", "osm_name_match", 239280639, None, None),
    ("Al-Baha Industrial City", "Al-Baha", "town_centre", None, 20.01, 41.47),
    ("Modon Oasis Al-Jouf", "Al-Jouf", "town_centre", None, 29.97, 40.21),
]

xlsx, extras_pbf, out = sys.argv[1:4]
raw = pd.read_excel(xlsx, header=None)
rows = raw.iloc[2:].dropna(subset=[1])
rows = rows[rows[0].astype(str).str.startswith("منطقة") | rows[0].astype(str).str.startswith("المنطقة")]
assert len(rows) == len(CITIES), (len(rows), len(CITIES))
osm = places.industrial_areas(extras_pbf).set_index("osm_id")

recs = []
for i, ((_, r), (name_en, region, method, osm_id, lat, lon)) in enumerate(zip(rows.iterrows(), CITIES), 1):
    if osm_id is not None:
        lat, lon = osm.loc[osm_id, "lat"], osm.loc[osm_id, "lon"]
    recs.append(dict(
        dest_id=f"MODON{i:02d}", name=name_en, name_ar=str(r[1]).strip(), region=region, region_ar=str(r[0]).strip(),
        type="industrial_city", lat=round(float(lat), 5), lon=round(float(lon), 5),
        developed_m2=round(float(r[2])), total_m2=round(float(r[3])), allocated_m2=round(float(r[4])),
        occupancy_pct=round(float(r[5]), 1),
        active_m2=round(float(r[2]) * float(r[5]) / 100),  # developed land in use: weight for results
        location_method=method, osm_id=osm_id, verified=False,
        source="MODON industrial cities data, March 2026; location: " + {
            "osm_name_match": "OpenStreetMap industrial area named as the city",
            "osm_probable": "OpenStreetMap industrial area in the town, not named as the city (verify)",
            "town_centre": "approximate town centre (verify)"}[method]))
df = pd.DataFrame(recs)
df["osm_id"] = df.osm_id.astype("Int64")
df.to_csv(out, index=False, encoding="utf-8")
print(f"{len(df)} cities -> {out}")
print(df.location_method.value_counts().to_string())
print(df[["dest_id", "name", "name_ar", "location_method", "lat", "lon", "developed_m2", "occupancy_pct"]].to_string(index=False))
