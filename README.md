# Jeddah port logistics

How transport constraints affect Saudi manufacturers moving raw materials through Jeddah Islamic Port, measured as road distance, travel time and (next) cost, with scenarios for port and strait closures.

## Notebooks

| Notebook | What it does | Open |
|---|---|---|
| `notebooks/01_routes.ipynb` | Builds the road network from OpenStreetMap, routes car and truck profiles from Jeddah Islamic Port to Saudi cities, adds IMF PortWatch seaport data, and writes everything to one GeoPackage for QGIS. | [Open in Colab](https://colab.research.google.com/github/danaalsh/jeddah-port-logistics/blob/main/notebooks/01_routes.ipynb) |

Outputs (GeoPackage, QGIS project, tables) are saved to `MyDrive/jeddah_port/` when run in Colab. They are rebuilt from the inputs on each run and are not stored in this repository.

## Data

The **Refresh data** workflow (`.github/workflows/refresh_data.yml`) runs every Tuesday and publishes the latest inputs to the [`data-latest` release](https://github.com/danaalsh/jeddah-port-logistics/releases/tag/data-latest). Run it by hand from the **Actions** tab → **Refresh data** → **Run workflow**.

| File | Source | Content |
|---|---|---|
| `gcc_major.osm.pbf` | OpenStreetMap via Geofabrik (GCC States extract) | Motorway to secondary roads in Saudi Arabia, UAE, Oman, Qatar, Bahrain, Kuwait |
| `gcc_extras.osm.pbf` | same | Industrial areas, ports, harbours, railways |
| `osm_date.txt` | same | OSM snapshot timestamp, for citation |
| `portwatch_ports_daily_SAU.csv` | IMF PortWatch | Daily ship calls and estimated trade by vessel type, Saudi ports, from 2019 |
| `portwatch_chokepoints_daily.csv` | IMF PortWatch | Daily transits through ~28 chokepoints (Hormuz, Bab el-Mandeb, Suez, ...) |
| `portwatch_ports_list.csv` | IMF PortWatch | ~2,000 ports with coordinates and trade shares |

Direct download link for any file: `https://github.com/danaalsh/jeddah-port-logistics/releases/download/data-latest/<file>`

## Scripts

| Script | Use |
|---|---|
| `scripts/refresh_osm.sh OUT_DIR` | Download and filter the GCC OSM extract (needs `osmium-tool`) |
| `scripts/refresh_portwatch.py OUT_DIR` | Download the three PortWatch datasets |
| `scripts/portwatch_charts.py DATA_DIR OUT_DIR` | Chokepoint, port-shift and export-mix charts |
| `scripts/qgis_style.py OUT_DIR` | Store layer styles in the GeoPackage and write the QGIS project (needs PyQGIS) |

`styles/` holds the QGIS layer styles (`.qml`); notebook section 8 re-applies them to a rebuilt GeoPackage.

## Attribution

- Road network: © OpenStreetMap contributors, available under the [Open Database License](https://www.openstreetmap.org/copyright).
- Port and chokepoint data: IMF PortWatch (portwatch.imf.org), estimates from AIS ship-tracking data.
- QGIS basemap: Esri Light Gray Canvas (Esri, HERE, Garmin, © OpenStreetMap contributors).
