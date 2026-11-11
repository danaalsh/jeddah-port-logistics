# Jeddah port logistics

How transport constraints affect Saudi manufacturers moving raw materials through Jeddah Islamic Port, measured as road distance, travel time and cost, with scenarios for port and strait closures.

## Notebooks

| Notebook | What it does | Open |
|---|---|---|
| `notebooks/01_routes.ipynb` | Builds the road network from OpenStreetMap, routes car and truck profiles from Jeddah Islamic Port to Saudi cities, adds IMF PortWatch seaport data, and writes everything to one GeoPackage for QGIS. | [Open in Colab](https://colab.research.google.com/github/danaalsh/jeddah-port-logistics/blob/main/notebooks/01_routes.ipynb) |
| `notebooks/02_scenarios.ipynb` | Scenario model: for each origin region and Saudi destination, the cheapest port in Saudi Arabia, the UAE or Oman and its full route and cost, under strait closures. Checks the Hormuz scenario against PortWatch. Adds `sim_*` layers to the GeoPackage. | [Open in Colab](https://colab.research.google.com/github/danaalsh/jeddah-port-logistics/blob/main/notebooks/02_scenarios.ipynb) |

Outputs (GeoPackage, QGIS project, tables) are saved to `MyDrive/jeddah_port/` when run in Colab. They are rebuilt from the inputs on each run and are not stored in this repository.

## Scenario model

Code in `sim/`, settings in `config/`. For every origin region (Asia via Shanghai, Europe via Rotterdam), destination and port:

| Leg | How it is computed | Cost per TEU |
|---|---|---|
| Sea: origin → port | Shortest sea route on the `searoute` maritime network; closed chokepoints are removed, so ships divert (e.g. around Africa) or the port becomes unreachable | distance rate + Suez fee + war-risk premiums for Bab el-Mandeb / Hormuz |
| Port | Handling and dwell time per port (`config/ports.csv`) | handling + storage per day |
| Road: port → destination | Cheapest truck route on the GCC road network (OSM), truck speed capped; border crossings (`config/border_crossings.csv`) add delay and fees | truck cost per km and per hour, border fees |

The model picks the option with the lowest **generalised cost**: money plus time valued at the cargo's inventory holding cost. Scenarios (`sim/model.py`, `SCENARIOS`): `baseline`, `hormuz_closed`, `babelmandeb_closed`, `both_closed`.

**Config files** (edit and rerun; no code changes needed):

| File | Content |
|---|---|
| `config/costs.csv` | Cost parameters. Most are placeholders marked `dummy`; replace them with sourced figures and fill in `source`. |
| `config/ports.csv` | Ports in the model (PortWatch IDs), handling cost and dwell days |
| `config/border_crossings.csv` | Border crossings (location from OSM border posts), delay and fee |
| `config/destinations.csv` | 12 major cities; `MyDrive/jeddah_port/sites.csv` adds your own sites |
| `config/industrial_cities_modon.csv` | The 37 MODON industrial cities (March 2026): developed, total and allocated area, occupancy, and **active area** (developed x occupancy) used to weight results. Location from OSM where the city could be matched; `location_method` says how (`osm_name_match`, `osm_probable`, `town_centre`), and the last two should be checked. Built by `scripts/modon_cities.py`. |

**Limitations of this first version:** costs are placeholders; ports and borders have no capacity limits or congestion; 22 of the 37 industrial cities are located approximately (probable OSM match or town centre); no rail; sea routes are shortest paths on a simplified maritime network.

Tests: `python -m pytest tests` (routing and border-delay checks on a hand-built network).

## Data

The **Refresh data** workflow (`.github/workflows/refresh_data.yml`) runs every Tuesday and publishes the latest inputs to the [`data-latest` release](https://github.com/danaalsh/jeddah-port-logistics/releases/tag/data-latest). Run it by hand from the **Actions** tab → **Refresh data** → **Run workflow**.

| File | Source | Content |
|---|---|---|
| `gcc_major.osm.pbf` | OpenStreetMap via Geofabrik (GCC States extract) | Motorway to secondary roads in Saudi Arabia, UAE, Oman, Qatar, Bahrain, Kuwait |
| `gcc_extras.osm.pbf` | same | Industrial areas, ports, harbours, railways |
| `osm_date.txt` | same | OSM snapshot timestamp, for citation |
| `portwatch_ports_daily_SAU.csv` | IMF PortWatch | Daily ship calls and estimated trade by vessel type, Saudi ports, from 2019 |
| `portwatch_ports_daily_ARE_OMN.csv` | IMF PortWatch | The same for UAE and Oman ports, from 2025 (to check where Gulf traffic went after Hormuz closed) |
| `portwatch_chokepoints_daily.csv` | IMF PortWatch | Daily transits through ~28 chokepoints (Hormuz, Bab el-Mandeb, Suez, ...) |
| `gpr_monthly.xls`, `gpr_daily.xls` | Geopolitical Risk Index, Caldara and Iacoviello (matteoiacoviello.com/gpr.htm) | Monthly global and country GPR (incl. Saudi Arabia) from 1900/1985; daily global GPR. Used for route risk scores |
| `portwatch_ports_list.csv` | IMF PortWatch | ~2,000 ports with coordinates and trade shares |

PortWatch's server cannot export the full daily tables reliably, so they are updated incrementally: each run starts from the copy in the release (or `data/seed/` on the first run), re-downloads the last two months plus anything newer one month at a time, and merges. A month that fails shows as a warning and keeps its previous rows.

Direct download link for any file: `https://github.com/danaalsh/jeddah-port-logistics/releases/download/data-latest/<file>`

## Scripts

| Script | Use |
|---|---|
| `scripts/refresh_osm.sh OUT_DIR` | Download and filter the GCC OSM extract (needs `osmium-tool`) |
| `scripts/refresh_portwatch.py OUT_DIR` | Download the three PortWatch datasets |
| `scripts/portwatch_charts.py DATA_DIR OUT_DIR` | Chokepoint, port-shift and export-mix charts |
| `scripts/qgis_style.py OUT_DIR` | Store layer styles in the GeoPackage and write the QGIS project (needs PyQGIS) |

`styles/` holds the QGIS layer styles (`.qml`); notebook section 8 re-applies them to a rebuilt GeoPackage.

## Other data in the repository

| File | Content |
|---|---|
| `data/modon/modon_services_2025.csv` | MODON services guide 2025: 69 services with Arabic text, English name and category (translated by Claude; check against the Arabic), number of steps and required documents, whether the industrial city's official decides, and logistics-related services (evening truck entry, equipment transport). Built by `scripts/modon_services.py`. Evidence for H2c. |
| `data/seed/` | PortWatch history used to start the incremental refresh |

## Attribution

- Road network: © OpenStreetMap contributors, available under the [Open Database License](https://www.openstreetmap.org/copyright).
- Port and chokepoint data: IMF PortWatch (portwatch.imf.org), estimates from AIS ship-tracking data.
- QGIS basemap: Esri Light Gray Canvas (Esri, HERE, Garmin, © OpenStreetMap contributors).
